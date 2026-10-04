"""Remembers every job ever seen (data/seen_jobs.sqlite) so each day's tab only holds NEW jobs.

Since 2026-09-25 it also holds what the 24x7 watcher needs between runs:
  source_state  when each source last ran, worked or failed, and when it is due again
  notified      which jobs you were already alerted about (never ping twice)
  link_checks   result of opening each good job's apply page (open, closed, location lock)
  custom_cvs    job-specific CVs already built (not rebuilt unless the template changes)
"""
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=60, check_same_thread=False)
        self._lock = threading.Lock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            key TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
            source TEXT, title TEXT, company TEXT, url TEXT, score INTEGER)""")
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if "found_at" not in cols:
            self.db.execute("ALTER TABLE jobs ADD COLUMN found_at TEXT")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (run_at TEXT, source TEXT, fetched INTEGER)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS source_state (
            name TEXT PRIMARY KEY, last_try TEXT, last_ok TEXT, fails INTEGER DEFAULT 0,
            next_due TEXT, last_status TEXT, last_count INTEGER)""")
        self.db.execute("CREATE TABLE IF NOT EXISTS notified (key TEXT PRIMARY KEY, at TEXT, score INTEGER)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS link_checks (
            key TEXT PRIMARY KEY, url TEXT, result TEXT, flag TEXT, checked_at TEXT)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS custom_cvs (
            key TEXT PRIMARY KEY, template TEXT, file TEXT, hash TEXT, built_at TEXT)""")
        # added 2026-09-26: job text for cover letters, taps on Telegram buttons, "Not relevant" feedback,
        # and job-specific cover letters
        self.db.execute("CREATE TABLE IF NOT EXISTS job_text (key TEXT PRIMARY KEY, text TEXT, updated TEXT)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS user_actions (
            key TEXT, status TEXT, at TEXT, via TEXT, applied INTEGER DEFAULT 0, note TEXT DEFAULT '')""")
        if "note" not in {r[1] for r in self.db.execute("PRAGMA table_info(user_actions)")}:
            self.db.execute("ALTER TABLE user_actions ADD COLUMN note TEXT DEFAULT ''")
        self.db.execute("CREATE TABLE IF NOT EXISTS feedback (key TEXT PRIMARY KEY, title TEXT, company TEXT, verdict TEXT, at TEXT)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS cover_letters (
            key TEXT PRIMARY KEY, file TEXT, hash TEXT, asked INTEGER, built_at TEXT)""")
        self.db.commit()

    # ---- jobs ----
    def first_seen(self, key: str) -> str | None:
        row = self.db.execute("SELECT first_seen FROM jobs WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def found_at(self, key: str) -> str | None:
        row = self.db.execute("SELECT found_at FROM jobs WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def upsert(self, job, today: date, found_at: str | None = None):
        with self._lock:
            self.db.execute("""INSERT INTO jobs (key, first_seen, last_seen, source, title, company, url, score, found_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen, score=excluded.score, url=excluded.url""",
                            (job.key, today.isoformat(), today.isoformat(), job.source, job.title,
                             job.company, job.url, job.score, found_at))

    def urls(self) -> dict[str, str]:
        """The apply link of every job, as last fetched. The workbook's hyperlinks are never read back as
        data: 113 rows carried another job's link on 2026-09-26 (an old shift, copied forward on every save)."""
        return {k: u for k, u in self.db.execute("SELECT key, url FROM jobs WHERE url LIKE 'http%'")}

    def remember(self, key: str, first_seen: str, row: dict):
        """Record a job that reached the workbook some other way (a merged side file) without
        touching jobs already known."""
        with self._lock:
            self.db.execute("INSERT OR IGNORE INTO jobs (key, first_seen, last_seen, source, title, company, url, score) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (key, first_seen, first_seen, row.get("Source"), row.get("Title"),
                             row.get("Company"), row.get("Apply link"), row.get("Score")))

    # ---- run history (silent-block detection) ----
    def usual_count(self, source: str, last_n: int = 5) -> int | None:
        """Median jobs fetched in this source's last few successful runs (None until there's history)."""
        rows = [r[0] for r in self.db.execute(
            "SELECT fetched FROM runs WHERE source=? AND fetched>0 ORDER BY run_at DESC LIMIT ?", (source, last_n))]
        return sorted(rows)[len(rows) // 2] if len(rows) >= 2 else None

    def record_run(self, run_at: str, source: str, fetched: int):
        with self._lock:
            self.db.execute("INSERT INTO runs VALUES (?,?,?)", (run_at, source, fetched))

    # ---- watcher: per-source schedule and health ----
    def source_state(self, name: str) -> dict:
        row = self.db.execute("SELECT name, last_try, last_ok, fails, next_due, last_status, last_count "
                              "FROM source_state WHERE name=?", (name,)).fetchone()
        keys = ["name", "last_try", "last_ok", "fails", "next_due", "last_status", "last_count"]
        return dict(zip(keys, row)) if row else {"name": name, "fails": 0}

    def all_source_states(self) -> list[dict]:
        keys = ["name", "last_try", "last_ok", "fails", "next_due", "last_status", "last_count"]
        return [dict(zip(keys, r)) for r in self.db.execute(
            "SELECT name, last_try, last_ok, fails, next_due, last_status, last_count FROM source_state ORDER BY name")]

    def record_source(self, name: str, ok: bool, status: str, count: int, every_minutes: int, now: datetime | None = None):
        """ok: schedule the next check after every_minutes. Failed: retry sooner at first (15, 30, 60 min…)
        then back off to at most 6 hours, so a blocked site is left alone instead of hammered."""
        now = now or datetime.now()
        prev = self.source_state(name)
        fails = 0 if ok else int(prev.get("fails") or 0) + 1
        if ok:
            wait = every_minutes
        else:
            wait = min(15 * 2 ** (fails - 1), 360)
        with self._lock:
            self.db.execute("""INSERT INTO source_state (name, last_try, last_ok, fails, next_due, last_status, last_count)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET last_try=excluded.last_try,
                last_ok=COALESCE(excluded.last_ok, source_state.last_ok), fails=excluded.fails,
                next_due=excluded.next_due, last_status=excluded.last_status, last_count=excluded.last_count""",
                            (name, now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds") if ok else None,
                             fails, (now + timedelta(minutes=wait)).isoformat(timespec="seconds"), status[:300], count))
            self.db.commit()
        return fails

    def postpone(self, name: str, minutes: int, status: str, now: datetime | None = None):
        """Check again soon without counting a failure (the internet was down, not the site)."""
        now = now or datetime.now()
        with self._lock:
            self.db.execute("""INSERT INTO source_state (name, last_try, fails, next_due, last_status)
                VALUES (?,?,0,?,?) ON CONFLICT(name) DO UPDATE SET last_try=excluded.last_try,
                next_due=excluded.next_due, last_status=excluded.last_status""",
                            (name, now.isoformat(timespec="seconds"),
                             (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"), status[:300]))
            self.db.commit()

    def last_ok(self, name: str) -> str | None:
        return self.source_state(name).get("last_ok")

    # ---- notifications ----
    def was_notified(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM notified WHERE key=?", (key,)).fetchone() is not None

    def mark_notified(self, keys_scores):
        with self._lock:
            self.db.executemany("INSERT OR IGNORE INTO notified VALUES (?,?,?)",
                                [(k, datetime.now().isoformat(timespec="seconds"), s) for k, s in keys_scores])
            self.db.commit()

    # ---- link checks ----
    def link_checks(self) -> dict[str, dict]:
        return {k: {"url": u, "result": r, "flag": f, "checked_at": c}
                for k, u, r, f, c in self.db.execute("SELECT key, url, result, flag, checked_at FROM link_checks")}

    def save_link_check(self, key: str, url: str, result: str, flag: str = ""):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO link_checks VALUES (?,?,?,?,?)",
                            (key, url, result, flag, datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    # ---- custom CVs ----
    def custom_cv(self, key: str) -> dict | None:
        row = self.db.execute("SELECT template, file, hash, built_at FROM custom_cvs WHERE key=?", (key,)).fetchone()
        return dict(zip(["template", "file", "hash", "built_at"], row)) if row else None

    def all_custom_cvs(self) -> dict[str, dict]:
        return {k: {"template": t, "file": f, "hash": h, "built_at": b}
                for k, t, f, h, b in self.db.execute("SELECT key, template, file, hash, built_at FROM custom_cvs")}

    def save_custom_cv(self, key: str, template: str, file: str, hash_: str):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO custom_cvs VALUES (?,?,?,?,?)",
                            (key, template, file, hash_, datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def forget_custom_cv(self, key: str):
        with self._lock:
            self.db.execute("DELETE FROM custom_cvs WHERE key=?", (key,))
            self.db.commit()

    # ---- job text ----
    def save_texts(self, items):
        with self._lock:
            self.db.executemany("INSERT OR REPLACE INTO job_text VALUES (?,?,?)",
                                [(k, t[:12000], datetime.now().isoformat(timespec="seconds")) for k, t in items if t])

    def text(self, key: str) -> str:
        row = self.db.execute("SELECT text FROM job_text WHERE key=?", (key,)).fetchone()
        return row[0] if row else ""

    # ---- actions from Telegram buttons (or anywhere outside the sheet) ----
    def add_action(self, key: str, status: str, via: str = "telegram", note: str = ""):
        with self._lock:
            self.db.execute("INSERT INTO user_actions (key, status, at, via, note) VALUES (?,?,?,?,?)",
                            (key, status, datetime.now().isoformat(timespec="seconds"), via, note))
            self.db.commit()

    def pending_actions(self) -> dict[str, tuple]:
        """Latest not-yet-saved action per job: key -> (status, at, note)."""
        out = {}
        for k, st, at, note in self.db.execute(
                "SELECT key, status, at, note FROM user_actions WHERE applied=0 ORDER BY at"):
            prev_note = out.get(k, ("", "", ""))[2]
            out[k] = (st, at, " | ".join(filter(None, [prev_note, note or ""])))
        return out

    def recent_actions(self, since: str) -> dict[str, tuple[str, str]]:
        out = {}
        for k, st, at in self.db.execute("SELECT key, status, at FROM user_actions WHERE at>=? ORDER BY at", (since,)):
            out[k] = (st, at)
        return out

    def mark_actions_saved(self, keys):
        with self._lock:
            self.db.executemany("UPDATE user_actions SET applied=1 WHERE key=?", [(k,) for k in keys])
            self.db.commit()

    # ---- "Not relevant" feedback, used to push similar jobs down ----
    def add_feedback(self, key: str, title: str, company: str, verdict: str = "Not relevant"):
        with self._lock:
            self.db.execute("INSERT OR IGNORE INTO feedback VALUES (?,?,?,?,?)",
                            (key, title, company, verdict, datetime.now().isoformat(timespec="seconds")))

    def feedback(self) -> list[tuple[str, str, str]]:
        return list(self.db.execute("SELECT key, title, company FROM feedback WHERE verdict='Not relevant'"))

    # ---- cover letters ----
    def cover_letter(self, key: str) -> dict | None:
        row = self.db.execute("SELECT file, hash, asked, built_at FROM cover_letters WHERE key=?", (key,)).fetchone()
        return dict(zip(["file", "hash", "asked", "built_at"], row)) if row else None

    def save_cover_letter(self, key: str, file: str, hash_: str, asked: bool):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO cover_letters VALUES (?,?,?,?,?)",
                            (key, file, hash_, int(asked), datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def commit(self):
        with self._lock:
            self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()
