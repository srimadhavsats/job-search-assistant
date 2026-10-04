"""24x7 job watcher (added 2026-09-25).

Every source has its own rhythm in config/sources.yaml (every_minutes): company career APIs and job
feeds every 20 to 30 minutes, LinkedIn hourly (newest posts only), Naukri and Apna a few times a day
because they block fast visitors. Each check runs only the sources that are due, so a new job
reaches your workbook and your alerts within about half an hour of being posted, without hammering
any site. A source that fails is retried after 15 minutes, then 30, 60… up to 6 hours, and you get
one alert a day if it keeps failing.

    python -m jobhunter.watch             one check now (Task Scheduler runs this every 15 minutes)
    python -m jobhunter.watch --loop      keep checking every 10 minutes (spare laptop, terminal)
    python -m jobhunter.watch --status    show each source's schedule and health
    python -m jobhunter.watch --force LinkedIn,Indeed    check these now, due or not

When started by Task Scheduler with pythonw (no window), output goes to output/watch.log.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from jobhunter import pipeline
from jobhunter.lock import RunLock
from jobhunter.store import SeenStore

ROOT = pipeline.ROOT
LOG_FILE = ROOT / "output" / "watch.log"
HEARTBEAT = ROOT / "data" / "watch_heartbeat.txt"


class _Log:
    """Timestamps every line. Writes to output/watch.log (kept under ~2 MB) and the console if any."""

    def __init__(self, to_console: bool):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
            tail = LOG_FILE.read_bytes()[-500_000:]
            LOG_FILE.write_bytes(tail)
        self.fh = open(LOG_FILE, "a", encoding="utf-8")
        self.console = to_console

    def __call__(self, msg: str):
        stamp = datetime.now().strftime("%m-%d %H:%M:%S")
        for line in str(msg).splitlines() or [""]:
            self.fh.write(f"{stamp} {line}\n")
            if self.console:
                try:
                    print(line, flush=True)
                except Exception:
                    self.console = False
        self.fh.flush()

    def close(self):
        self.fh.close()


MORNING = (9, 30)          # the first check at or after this time each day is a full search of every site
CATCH_UP_HOURS = 6         # a source not checked for this long (laptop off, no Wi-Fi) gets a full catch-up


def morning_pass_due(now: datetime | None = None, last_full: str | None = None) -> bool:
    """True for the first check after 09:30 each day that has not had a full search yet.

    Replaces relying on a 10:00 task: with the laptop off at 10:00 on 2026-09-26, Windows never ran it.
    The watcher starts at every login, so this runs at the first check after the laptop is back on."""
    now = now or datetime.now()
    if (now.hour, now.minute) < MORNING:
        return False
    if last_full is None:
        last_full = pipeline.LAST_FULL.read_text(encoding="utf-8").strip() if pipeline.LAST_FULL.exists() else ""
    return not last_full or last_full[:10] < now.date().isoformat()     # none yet today (a manual run counts)


def needs_catch_up(cfg: dict, state: dict, now: datetime | None = None) -> bool:
    """Quick checks look at recent posts only (JobStash today, LinkedIn's newest). After a long gap they
    would miss what was posted meanwhile, so that source runs once with its full settings."""
    now = now or datetime.now()
    last = state.get("last_ok")
    if not cfg.get("watch"):
        return False
    if not last:
        return True
    gap_min = (now - datetime.fromisoformat(last)).total_seconds() / 60
    return gap_min > max(CATCH_UP_HOURS * 60, 3 * pipeline.every_minutes(cfg))


def due_sources(cfgs: list[dict], store: SeenStore, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    due = []
    for c in cfgs:
        if pipeline.every_minutes(c) <= 0:
            continue
        nxt = store.source_state(c["name"]).get("next_due")
        if not nxt or datetime.fromisoformat(nxt) <= now:
            due.append(c)
    return due


def status(log=print) -> None:
    store = SeenStore(pipeline.DB)
    cfgs = pipeline.load_sources()
    now = datetime.now()
    log(f"{'Source':26} {'every':>6}  {'last OK':16}  {'next check':16}  fails  result")
    for c in cfgs:
        s = store.source_state(c["name"])
        nxt = (s.get("next_due") or "now").replace("T", " ")[:16]
        if s.get("next_due") and datetime.fromisoformat(s["next_due"]) <= now:
            nxt = "due now"
        log(f"{c['name'][:26]:26} {pipeline.every_minutes(c):>5}m  {(s.get('last_ok') or 'never').replace('T', ' ')[:16]:16}  "
            f"{nxt:16}  {s.get('fails') or 0:>5}  {(s.get('last_status') or '')[:70]}")
    if HEARTBEAT.exists():
        log(f"\nLast watcher check: {HEARTBEAT.read_text(encoding='utf-8').strip()}")
    store.close()


def tick(log, force: set[str] | None = None) -> int:
    lock = RunLock(ROOT / "data" / "run.lock")
    if not lock.acquire(wait_seconds=0):
        log("another run is busy (full search or an earlier check), skipping this check")
        return 0
    try:
        HEARTBEAT.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
        cfgs = pipeline.load_sources()
        store = SeenStore(pipeline.DB)
        morning = not force and morning_pass_due()
        if morning:
            due = cfgs
        else:
            due = [c for c in cfgs if c["name"].lower() in force] if force else due_sources(cfgs, store)
        catch_up = {c["name"] for c in due if needs_catch_up(c, store.source_state(c["name"]))}
        store.close()
        if not due:
            log("nothing due")
            return 0
        from jobhunter.main import wait_for_internet
        if not wait_for_internet(max_minutes=3):
            log("no internet, will try again at the next check")
            return 2
        from jobhunter import net
        net.reset_breakers()
        if morning:
            log("morning full search of every site (first check after 09:30 today)")
            pipeline.run(due, pipeline.load_profile(), mode="full", log=log, full_pass=True)
        else:
            pipeline.run(due, pipeline.load_profile(), mode="watch", log=log, full_names=catch_up)
        return 0
    except Exception as e:
        import traceback
        log(f"CHECK FAILED: {e!r}\n{traceback.format_exc()}")
        return 1
    finally:
        lock.release()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="keep checking")
    ap.add_argument("--every", type=float, default=10, help="minutes between checks with --loop")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", help="comma-separated source names to check now")
    args = ap.parse_args(argv)
    console = sys.stdout is not None
    if console:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            console = False
    log = _Log(console)
    try:
        if args.status:
            status(log)
            return 0
        force = {s.strip().lower() for s in args.force.split(",")} if args.force else None
        if not args.loop:
            return tick(log, force)
        while True:
            tick(log, force)
            force = None
            time.sleep(max(60, args.every * 60))
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
