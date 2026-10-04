"""One-click job search: every enabled source, now (run_jobs.bat, and the daily 10:00 safety run).

    python -m jobhunter.main                 # everything enabled in config/sources.yaml
    python -m jobhunter.main --only naukri   # just some sources (comma separated, by name)
    python -m jobhunter.main --days 30       # look further back this time

The 24x7 watcher (jobhunter/watch.py) runs the same pipeline for whichever sources are due. Both take
data/run.lock, so they never write the workbook at the same time; this waits for a watcher check to
finish instead of skipping.
"""
from __future__ import annotations

import argparse
import sys
import time

from jobhunter import pipeline
from jobhunter.lock import RunLock

ROOT = pipeline.ROOT
OUTPUT = pipeline.OUTPUT


def wait_for_internet(max_minutes: int = 15) -> bool:
    """Scheduled runs often start right after the laptop wakes, while Wi-Fi is still reconnecting,
    or during an outage. Starting then would make every source fail, so wait for a connection
    (checking every 30 s) instead of wasting the run."""
    import httpx
    deadline = time.time() + max_minutes * 60
    announced = False
    while True:
        for url in ("https://www.google.com/generate_204", "https://1.1.1.1"):
            try:
                httpx.head(url, timeout=8)
                if announced:
                    print("Internet is back — starting.", flush=True)
                return True
            except Exception:
                pass
        if time.time() > deadline:
            return False
        if not announced:
            print(f"No internet connection — waiting up to {max_minutes} min for it to come back…", flush=True)
            announced = True
        time.sleep(30)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source names")
    ap.add_argument("--days", type=int, help="override max_age_days")
    ap.add_argument("--no-alerts", action="store_true", help="don't send pop-up/Telegram alerts this time")
    args = ap.parse_args(argv)

    profile = pipeline.load_profile(args.days)
    wanted = {s.strip().lower() for s in args.only.split(",")} if args.only else None
    cfgs = pipeline.load_sources(wanted)
    if not cfgs:
        print("No enabled sources matched.")
        return 1

    lock = RunLock(ROOT / "data" / "run.lock")
    if not lock.acquire(wait_seconds=0):
        print("A watcher check is running right now. Waiting for it to finish (up to 50 minutes)…", flush=True)
        if not lock.acquire(wait_seconds=50 * 60):
            print("Still busy after 50 minutes. Try again later. Your workbook was not touched.")
            return 3
    try:
        if not wait_for_internet():
            print("Still no internet after 15 minutes — skipping this run. Your workbook was not touched. "
                  "The watcher (or run_jobs.bat) will catch up.")
            return 2
        pipeline.run(cfgs, profile, mode="full", log=lambda m: print(m, flush=True), notify_new=not args.no_alerts,
                     full_pass=not args.only)
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
