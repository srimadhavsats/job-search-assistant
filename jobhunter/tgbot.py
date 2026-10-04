"""Your job search in Telegram (added 2026-09-26).

    setup_telegram.bat                 connect your bot (paste the token there, it never leaves this laptop)
    python -m jobhunter.tgbot          run the bot (Task Scheduler starts it at login, hidden)
    python -m jobhunter.tgbot --test   send the menu and today's plan once

Menu buttons (always at the bottom of the chat): What now, Next job, Remote, Browse (every tab of the sheet
as a list with pages), Follow-ups, Gigs, Progress, Sheet (the workbook as a file), Help. Typing any word searches
every job in the sheet.
Every job card has buttons: Open job, Applied, Not relevant, Skip, CV (sends the PDF), Cover letter (PDF plus
form answers), Referral (the message to copy and a link to find the person). Tapping Applied, Skip or
Not relevant shows the next job straight away, and the workbook is updated within seconds when it is
closed, otherwise at the next check. Only your own chat (saved at setup) is answered.

The bot reads data/state.json (written after every check) and never opens the workbook.
"""
from __future__ import annotations

import html
import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
SECRET = ROOT / "config" / "telegram.yaml"
STATE = ROOT / "data" / "state.json"
OFFSET = ROOT / "data" / "tg_offset.txt"
LOG = ROOT / "output" / "bot.log"
API = "https://api.telegram.org/bot{token}/{method}"
MENU = {"keyboard": [["▶️ What now", "📋 Next job"], ["🌍 Remote", "🗂 Browse"], ["🔁 Follow-ups", "💰 Gigs"],
                     ["📊 Progress", "📎 Sheet"], ["📈 Stats", "❓ Help"]],
        "resize_keyboard": True, "is_persistent": True,
        "input_field_placeholder": "Type a word to search, like binance or kyc"}
STATUS_BY_CODE = {"a": "Applied", "n": "Not relevant", "s": "Skip", "i": "Interview", "r": "Rejected", "o": "Offer"}
DONE = ("Applied", "Interview", "Offer", "Rejected", "Skip", "Not relevant")
MARK = {"Applied": "✓", "Interview": "★", "Offer": "★", "Rejected": "✗", "Skip": "–", "Not relevant": "✗"}
PAGE = 8
LISTS = {  # name: (button label, heading)
    "queue": ("🎯 Apply Queue", "Apply Queue, the jobs worth applying to now"),
    "remote": ("🌍 Remote", "Remote jobs you can do from India"),
    "india": ("🇮🇳 India", "Jobs in India (office or hybrid)"),
    "new": ("🆕 New today", "Found today"),
    "gigs": ("💰 Gigs", "Bounties, gigs and part-time work"),
    "followups": ("🔁 Follow-ups", "Applied 5 to 21 days ago, time to follow up"),
    "applied": ("✅ My applications", "Jobs you acted on, newest first"),
    "all": ("📚 All jobs", "Every job in the sheet, best first"),
}
HELP = ("I show you what to do next in your job search, and every job in your sheet.\n\n"
        "▶️ What now, the plan for this hour and your next job\n"
        "📋 Next job, one job at a time with its CV and cover letter\n"
        "🌍 Remote, remote jobs you can do from India\n"
        "🗂 Browse, every tab of the sheet (queue, India, new today, gigs, your applications, all jobs)\n"
        "🔁 Follow-ups, jobs to follow up on, with the message to send\n"
        "💰 Gigs, paid tasks and bounties\n"
        "📊 Progress, today and this week against your targets\n"
        "📎 Sheet, the whole workbook as a file for your phone\n\n"
        "Type any word (binance, kyc, support, dubai) to search all jobs.\n\n"
        "On a job, tap ✅ Applied once you have applied, 👎 Not relevant if the job is wrong for you (similar jobs "
        "will show less), or ⏭ Skip to leave it. New good jobs also arrive here by themselves.")


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def load_secret() -> dict:
    if SECRET.exists():
        return yaml.safe_load(SECRET.read_text(encoding="utf-8")) or {}
    return {}


def configured() -> bool:
    s = load_secret()
    return bool(s.get("bot_token") and s.get("chat_id"))


class Bot:
    def __init__(self, token: str, chat_id: str | int | None = None):
        self.token, self.chat_id = token, str(chat_id) if chat_id else None
        self.http = httpx.Client(timeout=httpx.Timeout(70, connect=15))

    def call(self, method: str, files=None, **params):
        url = API.format(token=self.token, method=method)
        for attempt in range(3):
            try:
                if files:
                    r = self.http.post(url, data={k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                                  for k, v in params.items()}, files=files)
                else:
                    r = self.http.post(url, json=params)
                data = r.json()
                if data.get("ok"):
                    return data.get("result")
                if r.status_code == 429:
                    time.sleep(min(30, (data.get("parameters") or {}).get("retry_after", 5)))
                    continue
                return None
            except (httpx.TransportError, ValueError):
                time.sleep(3 * (attempt + 1))
        return None

    def send(self, text: str, markup=None, chat_id=None):
        return self.call("sendMessage", chat_id=chat_id or self.chat_id, text=text[:4000], parse_mode="HTML",
                         disable_web_page_preview=True, reply_markup=markup or MENU)

    def edit(self, message_id, text: str, markup=None):
        return self.call("editMessageText", chat_id=self.chat_id, message_id=message_id, text=text[:4000],
                         parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)

    def send_file(self, path: Path, caption: str = ""):
        with open(path, "rb") as fh:
            return self.call("sendDocument", files={"document": (path.name, fh, "application/octet-stream")},
                             chat_id=self.chat_id, caption=caption[:1000])


# ---------------- data ----------------
_cache: dict = {"mtime": None, "state": None}


def load_state() -> dict:
    """data/state.json, re-read only when a check has written a new one."""
    try:
        mtime = STATE.stat().st_mtime
        if _cache["mtime"] != mtime:
            _cache["state"], _cache["mtime"] = json.loads(STATE.read_text(encoding="utf-8")), mtime
        return _cache["state"]
    except (OSError, ValueError):
        return {"plan": {}, "rows": {}, "lists": {}, "generated": ""}


def acted(since: str = "") -> dict[str, tuple[str, str]]:
    """Actions already taken (Telegram taps not yet in the state file), key -> (status, at)."""
    from jobhunter.store import SeenStore
    store = SeenStore(ROOT / "data" / "seen_jobs.sqlite")
    try:
        return store.recent_actions(since or "2000-01-01")
    finally:
        store.close()


def status_of(row: dict, done: dict) -> str:
    return (done.get(row.get("Key")) or (str(row.get("Status") or "New"),))[0]


def card(row: dict, ctx: str = "", done: dict | None = None) -> tuple[str, dict]:
    """A job as a message with buttons. ctx ("remote|2") means it was opened from a list: the buttons then
    lead back to that list page instead of on to the next queue job."""
    status = status_of(row, done or {})
    lines = [f"<b>{esc(row.get('Title'))}</b>",
             f"{esc(row.get('Company'))}, {esc(row.get('Location') or row.get('Work mode') or 'location not given')}",
             f"Score {esc(row.get('Score'))}, {esc(row.get('Priority'))}",
             f"<b>Status</b> {MARK.get(status, '')} {esc(status)}" if status in DONE else "<b>Status</b> New, not applied yet"]
    if row.get("Salary"):
        lines.append(f"Pay {esc(row.get('Salary'))}")
    if row.get("Deadline"):
        lines.append(f"Deadline {esc(row.get('Deadline'))}")
    why = [w for w in str(row.get("Why it matched") or "").split(" | ") if w][:3]
    if why:
        lines.append("Why it fits " + esc(", ".join(why)))
    if row.get("Flags"):
        lines.append("Note " + esc(str(row.get("Flags"))[:200]))
    if row.get("Link check"):
        lines.append("Apply page " + esc(row.get("Link check")))
    if row.get("Notes"):
        lines.append("Your notes " + esc(str(row.get("Notes"))[:150]))
    if row.get("_kind") != "freelance":
        lines.append(f"CV to send {esc(row.get('CV') or 'General CV')}" +
                     (f", {esc(row.get('Cover letter'))} ready" if row.get("Cover letter") else ""))
    key, tail = row.get("Key"), (f"|{ctx}" if ctx else "")
    kb = []
    if row.get("Apply link"):
        kb.append([{"text": "🔗 Open job", "url": row["Apply link"]}])
    if row.get("_kind") != "freelance":
        kb.append([{"text": "📄 CV", "callback_data": f"cv|{key}"}, {"text": "✉️ Cover letter", "callback_data": f"cl|{key}"},
                   {"text": "🤝 Referral", "callback_data": f"rf|{key}"}])
    if status in ("Applied", "Interview"):
        kb.append([{"text": "Mark ★ Interview", "callback_data": f"i|{key}{tail}"}, {"text": "Mark ✗ Rejected", "callback_data": f"r|{key}{tail}"},
                   {"text": "Mark 🏆 Offer", "callback_data": f"o|{key}{tail}"}])
    else:
        kb.append([{"text": "✅ Mark applied", "callback_data": f"a|{key}{tail}"}, {"text": "👎 Not relevant", "callback_data": f"n|{key}{tail}"},
                   {"text": "⏭ Skip", "callback_data": f"s|{key}{tail}"}])
    kb.append([{"text": "⬅ Back to list", "callback_data": f"L|{ctx}"}] if ctx else [{"text": "➡️ Next job", "callback_data": "nx"}])
    return "\n".join(lines), {"inline_keyboard": kb}


def followup_card(row: dict) -> tuple[str, dict]:
    text = (f"<b>{esc(row.get('Title'))}</b>\n{esc(row.get('Company'))}, applied {esc(row.get('Days since'))} days ago\n\n"
            f"Message to send (put the person's name in place of NAME)\n<code>{esc(row.get('Follow-up message'))}</code>")
    key = row.get("Key")
    kb = []
    if row.get("_referrer"):
        kb.append([{"text": "👥 Find someone on the team", "url": row["_referrer"]}])
    if row.get("Apply link"):
        kb.append([{"text": "🔗 The job", "url": row["Apply link"]}])
    kb.append([{"text": "📨 Sent", "callback_data": f"fs|{key}"}, {"text": "★ Interview", "callback_data": f"i|{key}"},
               {"text": "✗ Rejected", "callback_data": f"r|{key}"}])
    return text, {"inline_keyboard": kb}


def list_label(row: dict, status: str) -> str:
    mark = f"{MARK[status]} " if status in MARK else ""
    title = str(row.get("Title") or "")
    company = str(row.get("Company") or "")
    text = f"{mark}{row.get('Score')}  {title[:38]}{', ' + company[:16] if company else ''}"
    return text[:62]


class Session:
    """What the bot has shown today, so "Next job" moves on without you having to act, and your last search."""

    def __init__(self, bot: Bot):
        self.bot, self.passed, self.day = bot, [], datetime.now().date()
        self.search_keys: list[str] = []
        self.search_word = ""

    def _fresh(self):
        if datetime.now().date() != self.day:
            self.passed, self.day = [], datetime.now().date()

    def queue(self) -> tuple[list[str], dict]:
        state = load_state()
        done = acted(str(state.get("generated") or ""))
        rows = state.get("rows", {})
        keys = [k for k in (state.get("plan") or {}).get("queue", []) if k in rows and k not in done]
        return keys, rows

    def next_job(self, skip_current: bool = False):
        self._fresh()
        keys, rows = self.queue()
        todo = [k for k in keys if k not in self.passed]
        if not todo and self.passed:
            self.passed = []
            todo = keys
        if not todo:
            return self.bot.send("No job waiting in the queue right now. New good jobs will arrive here by themselves. "
                                 "Meanwhile try 🔁 Follow-ups or 💰 Gigs.")
        key = todo[0]
        self.passed.append(key)
        left = len(todo) - 1
        text, kb = card(rows[key])
        return self.bot.send(text + f"\n\n{left} more in the queue", kb)

    # ---------------- lists ----------------
    def list_keys(self, name: str) -> tuple[list[str], dict, dict]:
        state = load_state()
        rows = state.get("rows", {})
        done = acted(str(state.get("generated") or ""))
        if name == "search":
            keys = self.search_keys
        else:
            keys = (state.get("lists") or {}).get(name) or []
            if name in ("queue", "remote", "new", "gigs", "india", "followups"):
                keys = [k for k in keys if k not in done]     # tapped already, it leaves these lists at once
        return [k for k in keys if k in rows], rows, done

    def browse(self, message_id=None):
        state = load_state()
        counts = {n: len(self.list_keys(n)[0]) for n in LISTS}
        kb = [[{"text": f"{LISTS[a][0]} ({counts[a]})", "callback_data": f"L|{a}|0"},
                {"text": f"{LISTS[b][0]} ({counts[b]})", "callback_data": f"L|{b}|0"}]
              for a, b in (("queue", "remote"), ("india", "new"), ("gigs", "followups"), ("applied", "all"))]
        kb.append([{"text": "📎 Get the whole sheet", "callback_data": "SH"}])
        updated = str(state.get("generated") or "").replace("T", " ")[:16]
        text = f"<b>Your job sheet</b>, updated {esc(updated)}\nPick a list. You can also type any word to search."
        return self.bot.edit(message_id, text, {"inline_keyboard": kb}) if message_id else self.bot.send(text, {"inline_keyboard": kb})

    def show_list(self, name: str, page: int = 0, message_id=None):
        keys, rows, done = self.list_keys(name)
        pages = max(1, (len(keys) + PAGE - 1) // PAGE)
        page = max(0, min(page, pages - 1))
        heading = f"Search for \"{esc(self.search_word)}\"" if name == "search" else LISTS.get(name, (name, name))[1]
        if not keys:
            text = f"<b>{heading}</b>\nNothing here right now."
            kb = {"inline_keyboard": [[{"text": "🗂 Other lists", "callback_data": "B"}]]}
        else:
            text = (f"<b>{heading}</b>\n{len(keys)} job{'s' if len(keys) != 1 else ''}, page {page + 1} of {pages}. "
                    f"Tap one to open it.")
            buttons = []
            for k in keys[page * PAGE:(page + 1) * PAGE]:
                buttons.append([{"text": list_label(rows[k], status_of(rows[k], done)), "callback_data": f"J|{k}|{name}|{page}"}])
            nav = []
            if page > 0:
                nav.append({"text": "◀ Prev", "callback_data": f"L|{name}|{page - 1}"})
            nav.append({"text": "🗂 Lists", "callback_data": "B"})
            if page < pages - 1:
                nav.append({"text": "Next ▶", "callback_data": f"L|{name}|{page + 1}"})
            kb = {"inline_keyboard": buttons + [nav]}
        return self.bot.edit(message_id, text, kb) if message_id else self.bot.send(text, kb)

    def search(self, word: str):
        state = load_state()
        rows = state.get("rows", {})
        terms = [t for t in re.split(r"\s+", word.lower()) if t]
        order = {k: i for i, k in enumerate((state.get("lists") or {}).get("all") or [])}
        hits = [k for k, r in rows.items()
                if all(t in f"{r.get('Title')} {r.get('Company')} {r.get('Location')} {r.get('Source')}".lower() for t in terms)]
        hits.sort(key=lambda k: (str(rows[k].get("Status") or "New") != "New", order.get(k, 10**6), -float(rows[k].get("Score") or 0)))
        self.search_keys, self.search_word = hits, word
        return self.show_list("search", 0)

    def send_sheet(self):
        path = ROOT / "output" / "Jobs.xlsx"
        if not path.exists():
            return self.bot.send("The sheet is not there yet.")
        when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %H.%M")
        self.bot.send_file(path, f"Your job sheet, updated {when}. Open it with Excel or Google Sheets. Changes made in "
                                 f"this phone copy do not come back, so mark jobs with the buttons here.")

    # ---------------- plan and progress ----------------
    def what_now(self):
        from jobhunter import plan as planner
        state = load_state()
        p = state.get("plan") or {}
        if not p:
            return self.bot.send("No plan yet. It appears after the next check (within 15 minutes).")
        done = acted(str(state.get("generated") or ""))
        extra_applied = sum(1 for st, at in done.values() if st == "Applied" and at[:10] == datetime.now().date().isoformat())
        p = {**p, "applied_today": p.get("applied_today", 0) + extra_applied,
             "applied_week": p.get("applied_week", 0) + extra_applied, "slot": planner.slot(datetime.now()),
             "time": datetime.now().strftime("%H.%M"), "jobs": [], "followups": [], "gig": None}
        lines = [f"<b>{esc(planner.headline(p))}</b>", "",
                 f"Applied today {p['applied_today']} of {p.get('daily_target', 5)}, this week {p['applied_week']} of "
                 f"{p.get('weekly_target', 25)}",
                 f"Queue {p.get('queue_size', 0)} jobs ({p.get('new_today', 0)} new today), follow-ups due {p.get('followups_due', 0)}"]
        s = p["slot"]
        if s.get("name"):
            lines += ["", f"<b>Right now ({esc(s['time'])}) {esc(s['name'])}</b>", esc(s["what"]) +
                      (f" Target {esc(s['target'])}." if s.get("target") else "")]
        self.bot.send("\n".join(lines))
        return self.next_job()

    def followups(self):
        state = load_state()
        rows = state.get("rows", {})
        done = acted(str(state.get("generated") or ""))
        keys = [k for k in (state.get("plan") or {}).get("followups", []) if k in rows and k not in done]
        if not keys:
            return self.bot.send("No follow-ups due. They appear 5 days after you mark a job Applied.")
        for k in keys[:3]:
            text, kb = followup_card(rows[k])
            self.bot.send(text, kb)
        if len(keys) > 3:
            self.bot.send(f"{len(keys) - 3} more are due.", {"inline_keyboard": [[{"text": "🔁 See all follow-ups",
                                                                                     "callback_data": "L|followups|0"}]]})

    def stats(self):
        """How many good jobs per kind of role are waiting, applied, at interview or skipped."""
        state = load_state()
        st = state.get("stats") or {}
        rows = st.get("rows") or []
        if not rows:
            return self.bot.send("No stats yet. They appear after the next check (within 15 minutes).")
        done = acted(str(state.get("generated") or ""))
        head = f"{'Kind of role':<13}{'To do':>6}{'Appl':>5}{'Int':>4}{'Skip':>5}"
        lines = [head, "-" * len(head)]
        for r in rows:
            lines.append(f"{r['name'][:13]:<13}{r['todo']:>6}{r['applied']:>5}{r['interview']:>4}{r['skipped']:>5}")
        t = st.get("total") or {}
        lines += ["-" * len(head), f"{'Total':<13}{t.get('todo', 0):>6}{t.get('applied', 0):>5}{t.get('interview', 0):>4}{t.get('skipped', 0):>5}"]
        where = st.get("where") or {}
        extra = sum(1 for s, _ in done.values() if s == "Applied")
        self.bot.send("<b>Stats</b> (jobs scoring 55 or more)\n<pre>" + esc("\n".join(lines)) + "</pre>\n"
                      f"To do by place. Remote {where.get('remote', 0)}, India {where.get('india', 0)}, abroad {where.get('abroad', 0)}\n"
                      f"Gigs open {st.get('gigs', 0)}. New today {st.get('new_today', 0)}. Applied this week "
                      f"{(state.get('plan') or {}).get('applied_week', 0) + extra} of 25\n"
                      + (f"({extra} tap{'s' if extra != 1 else ''} from here still being written into the sheet)\n" if extra else "")
                      + "\n<i>To do</i> means in the Apply Queue. <i>Skip</i> includes Not relevant.",
                      {"inline_keyboard": [[{"text": "🎯 Apply Queue", "callback_data": "L|queue|0"},
                                            {"text": "✅ My applications", "callback_data": "L|applied|0"}]]})

    def progress(self):
        state = load_state()
        p = state.get("plan") or {}
        health = ""
        try:
            from jobhunter.store import SeenStore
            store = SeenStore(ROOT / "data" / "seen_jobs.sqlite")
            bad = [s["name"] for s in store.all_source_states() if (s.get("fails") or 0) >= 2]
            store.close()
            health = "All job sites are working." if not bad else f"Having trouble with {', '.join(bad)}."
        except Exception:
            pass
        hb = (ROOT / "data" / "watch_heartbeat.txt")
        last = hb.read_text(encoding="utf-8").strip().replace("T", " ")[:16] if hb.exists() else "unknown"
        lists = state.get("lists") or {}
        self.bot.send("\n".join([
            f"Applied today {p.get('applied_today', 0)} of {p.get('daily_target', 5)}",
            f"This week {p.get('applied_week', 0)} of {p.get('weekly_target', 25)}",
            f"Queue {p.get('queue_size', 0)} jobs, {p.get('new_today', 0)} new today",
            f"Remote jobs open to you {len(lists.get('remote') or [])}",
            f"Follow-ups due {p.get('followups_due', 0)}",
            f"Jobs you acted on {len(lists.get('applied') or [])}", "",
            f"Last check {esc(last)}. {esc(health)}"]))

    # ---------------- button taps ----------------
    def on_callback(self, cq: dict):
        parts = str(cq.get("data") or "").split("|")
        code, key = parts[0], (parts[1] if len(parts) > 1 else "")
        msg = cq.get("message") or {}
        mid = msg.get("message_id")
        state = load_state()
        row = state.get("rows", {}).get(key, {})
        answer = ""
        if code == "B":
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"])
            return self.browse(mid)
        if code == "L":
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"])
            return self.show_list(parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0, mid)
        if code == "J":
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"])
            if not row:
                return self.bot.send("That job is no longer in the sheet.")
            if parts[2:3] == ["followups"]:
                text, kb = followup_card(row)
            else:
                text, kb = card(row, "|".join(parts[2:4]), acted(str(state.get("generated") or "")))
            return self.bot.send(text, kb)
        if code == "SH":
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"], text="Sending the sheet")
            return self.send_sheet()
        if code in STATUS_BY_CODE:
            status = STATUS_BY_CODE[code]
            record(key, status)
            ctx = "|".join(parts[2:4])
            back = [[{"text": "⬅ Back to list", "callback_data": f"L|{ctx}"}]] if ctx else []
            self.bot.call("editMessageReplyMarkup", chat_id=self.bot.chat_id, message_id=mid,
                          reply_markup={"inline_keyboard": [[{"text": f"✔ Marked {status}", "callback_data": "noop"},
                                                             {"text": "↩ Undo", "callback_data": f"u|{key}" + (f"|{ctx}" if ctx else "")}]] + back})
            sync_soon()
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"], text=f"Marked {status}. Tap Undo if that was a mistake.")
            if code in ("a", "n", "s") and not ctx:
                return self.next_job()
            return None
        if code == "u":
            before = str(row.get("Status") or "New")
            record(key, before if before not in ("", "None") else "New")
            ctx = "|".join(parts[2:4])
            text, kb = card({**row, "Status": before}, ctx)
            self.bot.call("editMessageReplyMarkup", chat_id=self.bot.chat_id, message_id=mid, reply_markup=kb)
            sync_soon()
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"], text=f"Undone, back to {before}")
            return None
        if code == "fs":
            record(key, "Applied", note=f"followed up {datetime.now():%d %b}")
            answer = "Noted, follow-up sent"
            self.bot.call("editMessageReplyMarkup", chat_id=self.bot.chat_id, message_id=mid,
                          reply_markup={"inline_keyboard": [[{"text": "✔ Follow-up sent", "callback_data": "noop"}]]})
            sync_soon()
        elif code == "cv":
            path = _file(row.get("_cv_link"))
            answer = "Sending the CV" if path else "No CV file for this job yet"
            if path:
                self.bot.send_file(path, f"CV for {row.get('Title')} at {row.get('Company')}")
        elif code == "cl":
            path = _file(row.get("_cl_link"))
            if path:
                answer = "Sending the cover letter"
                self.bot.send_file(path, f"Cover letter for {row.get('Title')} at {row.get('Company')}")
                txt = path.with_suffix(".txt")
                if txt.exists():
                    answers = txt.read_text(encoding="utf-8").split("FORM ANSWERS", 1)
                    if len(answers) == 2:
                        self.bot.send("<b>Form answers</b>\n<code>" + esc(answers[1].strip()[:3500]) + "</code>")
            else:
                answer = "No cover letter for this job yet (only jobs in the Apply Queue get one)"
        elif code == "rf":
            answer = "Referral message"
            kb = {"inline_keyboard": [[{"text": "👥 Find someone on the team", "url": row["_referrer"]}]]} if row.get("_referrer") else None
            msg_text = row.get("Referral message") or "This job has no referral message yet (only Apply Queue jobs get one)."
            self.bot.send("Send this on LinkedIn to someone on the team (put their name in place of NAME)\n\n<code>"
                          + esc(msg_text) + "</code>", kb)
        elif code == "nx":
            self.bot.call("answerCallbackQuery", callback_query_id=cq["id"])
            return self.next_job()
        self.bot.call("answerCallbackQuery", callback_query_id=cq["id"], text=answer[:190])

    def on_message(self, msg: dict):
        raw = str(msg.get("text") or "").strip()
        text = raw.lower()
        routes = {
            ("/start", "/help", "❓ help", "help"): lambda: self.bot.send(HELP),
            ("/now", "▶️ what now", "what now", "now"): self.what_now,
            ("/next", "📋 next job", "next job", "next"): self.next_job,
            ("/remote", "🌍 remote", "remote"): lambda: self.show_list("remote"),
            ("/browse", "🗂 browse", "browse", "/lists", "lists"): self.browse,
            ("/followups", "🔁 follow-ups", "follow-ups", "followups"): self.followups,
            ("/gig", "/gigs", "💰 gig", "💰 gigs", "gig", "gigs"): lambda: self.show_list("gigs"),
            ("/progress", "📊 progress", "progress"): self.progress,
            ("/stats", "📈 stats", "stats"): self.stats,
            ("/sheet", "📎 sheet", "sheet"): self.send_sheet,
            ("/applied", "my applications", "applied"): lambda: self.show_list("applied"),
            ("/india", "india"): lambda: self.show_list("india"),
            ("/new", "new today", "new"): lambda: self.show_list("new"),
        }
        for words, action in routes.items():
            if text in words:
                return action()
        if len(text) >= 2 and not text.startswith("/"):
            return self.search(raw)
        return self.bot.send("Tap a button below, or type a word to search. ▶️ What now is the best place to start.")


def _file(link) -> Path | None:
    if not link:
        return None
    p = (ROOT / "output" / str(link)).resolve()
    return p if p.exists() else None


def record(key: str, status: str, note: str = ""):
    from jobhunter.store import SeenStore
    store = SeenStore(ROOT / "data" / "seen_jobs.sqlite")
    try:
        store.add_action(key, status, "telegram", note)
    finally:
        store.close()


_sync_lock = threading.Lock()


def sync_soon():
    """Write the taps into the workbook now if nothing else is running (else the next check does it)."""
    def work():
        if not _sync_lock.acquire(blocking=False):
            return
        try:
            time.sleep(4)            # several taps in a row become one save
            from jobhunter import pipeline
            pipeline.sync(log=lambda m: _log(f"sync {m}"))
        except Exception as e:
            _log(f"sync failed {e!r}")
        finally:
            _sync_lock.release()
    threading.Thread(target=work, daemon=True).start()


def _log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.write_bytes(LOG.read_bytes()[-200_000:])
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now():%m-%d %H:%M:%S} {msg}\n")


# ---------------- push messages (called by the watcher) ----------------
def push_card(row: dict, heading: str = "") -> bool:
    s = load_secret()
    if not (s.get("bot_token") and s.get("chat_id")):
        return False
    bot = Bot(s["bot_token"], s["chat_id"])
    text, kb = card(row)
    return bool(bot.send((f"<b>{esc(heading)}</b>\n" if heading else "") + text, kb))


def push_text(text_html: str) -> bool:
    s = load_secret()
    if not (s.get("bot_token") and s.get("chat_id")):
        return False
    return bool(Bot(s["bot_token"], s["chat_id"]).send(text_html))


def daily_messages(store, log=print) -> None:
    """Morning plan (first check after 09.30) and evening review (first check after 20.00), once a day each."""
    if not configured():
        return
    now = datetime.now()
    today = now.date().isoformat()
    state = load_state()
    p = state.get("plan") or {}
    if not p:
        return
    from jobhunter import plan as planner
    if (now.hour, now.minute) >= (9, 30) and not store.was_notified(f"plan:{today}"):
        p2 = {**p, "slot": planner.slot(now), "jobs": [], "followups": [], "gig": None}
        push_text(f"<b>Good morning. {esc(planner.headline(p2))}</b>\n\n"
                  f"{p.get('queue_size', 0)} jobs in the queue ({p.get('new_today', 0)} new since yesterday), "
                  f"{p.get('followups_due', 0)} follow-ups due. Tap ▶️ What now to start with job 1.")
        store.mark_notified([(f"plan:{today}", 0)])
        log("sent the morning plan to Telegram")
    if now.hour >= 20 and not store.was_notified(f"evening:{today}"):
        left = max(0, p.get("daily_target", 5) - p.get("applied_today", 0))
        push_text(f"<b>Evening check</b>\nApplied today {p.get('applied_today', 0)} of {p.get('daily_target', 5)}"
                  + (f", {left} to go. One more is still possible tonight." if left else ". Target done, well done.")
                  + f"\nFollow-ups due {p.get('followups_due', 0)}. Check email, including Spam and Promotions.")
        store.mark_notified([(f"evening:{today}", 0)])
        log("sent the evening check to Telegram")


# ---------------- setup and main loop ----------------
def setup() -> int:
    import getpass
    print("Connect your Telegram bot\n")
    print("1. In Telegram you already created a bot with @BotFather. It gave you a token that looks like")
    print("   123456789:ABCdef...  Copy it.")
    token = getpass.getpass("2. Paste the token here (it stays hidden while you paste) and press Enter: ").strip()
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", token):
        print("That does not look like a bot token. Run setup_telegram.bat again and paste the whole token.")
        return 1
    bot = Bot(token)
    me = bot.call("getMe")
    if not me:
        print("Telegram did not accept that token (or there is no internet). Check it and try again.")
        return 1
    name = me.get("username")
    print(f"\nToken works, your bot is @{name}.")
    print(f"3. Now open Telegram, search for @{name} (or open t.me/{name}) and press START.")
    print("   Waiting up to 5 minutes for your message...")
    bot.call("deleteWebhook")
    chat, offset, deadline = None, None, time.time() + 300
    while time.time() < deadline and not chat:
        updates = bot.call("getUpdates", timeout=30, offset=offset) or []
        for u in updates:
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if (m.get("chat") or {}).get("type") == "private":
                chat = m["chat"]
                break
    if not chat:
        print("No message arrived. Run setup_telegram.bat again and press START in your bot's chat.")
        return 1
    SECRET.write_text(yaml.safe_dump({"bot_token": token, "chat_id": str(chat["id"]), "username": name,
                                      "connected": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    OFFSET.write_text(str(offset or 0), encoding="utf-8")
    bot.chat_id = str(chat["id"])
    print(f"\nConnected to {chat.get('first_name', 'you')}. Only this chat will be answered.")
    bot.send(f"Connected. Hi {esc(chat.get('first_name', ''))}. " + HELP)
    Session(bot).what_now()
    return 0


def run() -> int:
    s = load_secret()
    if not (s.get("bot_token") and s.get("chat_id")):
        _log("not set up yet, run setup_telegram.bat")
        return 1
    bot = Bot(s["bot_token"], s["chat_id"])
    session = Session(bot)
    offset = int(OFFSET.read_text().strip()) if OFFSET.exists() and OFFSET.read_text().strip().isdigit() else None
    _log("bot started")
    wait = 5
    while True:
        try:
            updates = bot.call("getUpdates", timeout=50, offset=offset, allowed_updates=["message", "callback_query"])
            if updates is None:
                raise ConnectionError("no answer from Telegram")
            wait = 5
            for u in updates:
                offset = u["update_id"] + 1
                OFFSET.write_text(str(offset), encoding="utf-8")
                chat = ((u.get("message") or {}).get("chat") or (u.get("callback_query") or {}).get("message", {}).get("chat") or {})
                if str(chat.get("id")) != str(bot.chat_id):
                    continue                     # never answer anyone else
                try:
                    if u.get("callback_query"):
                        session.on_callback(u["callback_query"])
                    elif u.get("message"):
                        session.on_message(u["message"])
                except Exception as e:
                    _log(f"handler error {e!r}")
                    bot.send("Something went wrong on my side. Try the button again in a minute.")
        except Exception as e:          # no internet, laptop waking up: wait and try again, forever
            _log(f"waiting for Telegram ({e!r})"[:200])
            time.sleep(wait)
            wait = min(wait * 2, 120)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--setup" in argv:
        return setup()
    if "--test" in argv:
        s = load_secret()
        if not s.get("bot_token"):
            print("Not set up yet. Run setup_telegram.bat first.")
            return 1
        bot = Bot(s["bot_token"], s["chat_id"])
        bot.send(HELP)
        Session(bot).what_now()
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
