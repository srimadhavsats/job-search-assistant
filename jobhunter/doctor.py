"""System check, the "test demo" (added 2026-09-25). Double-click check_system.bat.

Runs every enabled source with a tiny search (one query, one page), then checks everything around it:
internet, disk space, Google Chrome and CV rendering, the workbook, the scheduled tasks, the watcher's
last check, and the alert channels. Prints PASS / WARN / FAIL per line and never touches the workbook.

    python -m jobhunter.doctor              everything
    python -m jobhunter.doctor --sources    only the job sites
    python -m jobhunter.doctor --popup      also show a test pop-up (and Telegram message if set up)
"""
from __future__ import annotations

import argparse
import copy
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from jobhunter import pipeline, sources

ROOT = pipeline.ROOT
LIST_KEYS = ("queries", "searches", "urls", "channels", "boards", "sites", "himalayas_queries", "jobicy_tags")


def smoke_cfg(cfg: dict) -> dict:
    """The smallest useful version of a source's settings."""
    c = copy.deepcopy(cfg)
    for k in LIST_KEYS:
        if isinstance(c.get(k), list) and c[k]:
            c[k] = c[k][:1]
    for k in ("companies", "getro", "consider"):
        if isinstance(c.get(k), dict) and c[k]:
            c[k] = dict(list(c[k].items())[:2])
    for k in ("pages", "pages_per_search", "max_details"):
        if k in c:
            c[k] = 1
    if isinstance(c.get("channels"), list):
        c["channels"] = [{**ch, "pages": 1} for ch in c["channels"]]
    c.update({"fresh_results_per_search": 10, "results_per_search": 10, "max_descriptions": 2,
              "backfill_every_hours": 10_000, "results": 10})
    return c


def smoke_profile(profile: dict) -> dict:
    p = copy.deepcopy(profile)
    for k in ("linkedin_searches", "naukri_searches", "naukrigulf_searches"):
        if p.get(k):
            p[k] = p[k][:1]
    if p.get("naukri_searches"):
        first = p["naukri_searches"][0]
        p["naukri_searches"] = [{"q": first["q"] if isinstance(first, dict) else first, "pages": 1}]
    p["linkedin_locations"] = (p.get("linkedin_locations") or [{"location": "India"}])[:1]
    return p


def check_source(cfg: dict, profile: dict) -> tuple[str, str, int, float, str]:
    started = time.time()
    notes = []
    try:
        jobs = sources.load(cfg).fetch(cfg, profile, lambda m: notes.append(m))
        warn = [n for n in notes if any(w in n.lower() for w in pipeline.WARNING_WORDS)]
        verdict = "PASS" if jobs and not warn else ("WARN" if jobs or warn else "WARN")
        detail = (warn[-1] if warn else (notes[-1] if notes else ""))[:90]
        if not jobs:
            detail = "0 jobs from the test search (may be normal for a tiny search). " + detail
        return cfg["name"], verdict, len(jobs), time.time() - started, detail
    except Exception as e:
        return cfg["name"], "FAIL", 0, time.time() - started, f"{e!r}"[:120]


def line(verdict: str, what: str, detail: str = ""):
    print(f"  {verdict:4}  {what:34} {detail}", flush=True)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", action="store_true", help="only test the job sites")
    ap.add_argument("--popup", action="store_true", help="send a test alert")
    ap.add_argument("--only", help="comma-separated source names")
    args = ap.parse_args(argv)
    fails = 0
    print(f"System check {datetime.now():%Y-%m-%d %H:%M}\n")

    if not args.sources:
        print("Basics")
        from jobhunter.main import wait_for_internet
        ok = wait_for_internet(max_minutes=0)
        line("PASS" if ok else "FAIL", "Internet", "")
        fails += not ok
        for drive in {ROOT.drive or "/", Path.home().drive or "/"}:
            free = shutil.disk_usage(drive + "\\" if drive.endswith(":") else drive).free // 2**30
            line("PASS" if free >= 2 else "WARN" if free >= 1 else "FAIL", f"Free space on {drive}", f"{free} GB")
        wb = ROOT / "output" / "Jobs.xlsx"
        from jobhunter.excel import _is_open, side_files
        line("PASS" if wb.exists() else "WARN", "Workbook exists", str(wb))
        if wb.exists():
            line("WARN" if _is_open(wb) else "PASS", "Workbook closed",
                 "open now, new results wait in a side file until you close it" if _is_open(wb) else "")
        sides = side_files(wb)
        line("PASS" if not sides else "WARN", "No waiting side files", ", ".join(s.name for s in sides))
        try:
            from jobhunter import cv
            out = ROOT / "data" / "doctor_test_cv.pdf"
            n = cv.render([("<html><body><h1>Test</h1></body></html>", out)], log=lambda m: None)
            line("PASS" if n and out.exists() else "FAIL", "Chrome renders PDFs", "")
            fails += not n
            out.unlink(missing_ok=True)
            cfg = cv.load_config()
            for tid, t in cfg["templates"].items():
                src = ROOT / t["html"]
                bad = cv.visible_banned(src.read_text(encoding="utf-8")) if src.exists() else ["missing"]
                line("PASS" if not bad else "FAIL", f"CV template {tid}", f"banned marks {bad[:2]}" if bad else t["html"])
                fails += bool(bad)
        except Exception as e:
            line("FAIL", "Chrome renders PDFs", f"{e!r}"[:100])
            fails += 1

        print("\nSchedules")
        r = subprocess.run(["schtasks", "/Query", "/TN", "Job Search Watcher", "/FO", "LIST"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        nxt = next((l.split(":", 1)[1].strip() for l in r.stdout.splitlines() if l.startswith("Next Run Time")), "")
        line("PASS" if r.returncode == 0 else "FAIL", "Task 'Job Search Watcher'",
             f"next run {nxt}" if nxt else "not registered, run setup_watcher.bat")
        fails += r.returncode != 0
        full = pipeline.LAST_FULL.read_text(encoding="utf-8").strip() if pipeline.LAST_FULL.exists() else ""
        line("PASS" if full[:10] == datetime.now().date().isoformat() or datetime.now().hour < 10 else "WARN",
             "Morning full search", f"last one {full.replace('T', ' ')[:16]}" if full else "none yet, the watcher does one after 09:30")
        hb = ROOT / "data" / "watch_heartbeat.txt"
        if hb.exists():
            age = (datetime.now() - datetime.fromisoformat(hb.read_text(encoding="utf-8").strip())).total_seconds() / 60
            line("PASS" if age < 40 else "WARN", "Watcher checked recently", f"{age:.0f} min ago")
        else:
            line("WARN", "Watcher checked recently", "no check yet")

        print("\nAlerts")
        from jobhunter import notify
        ncfg = notify.load_config()
        line("PASS" if ncfg.get("windows_popup", True) else "WARN", "Windows pop-ups", "on" if ncfg.get("windows_popup", True) else "off")
        tg = ncfg.get("telegram") or {}
        if tg.get("bot_token") and not tg.get("chat_id"):
            chat = notify.telegram_chat_id(tg["bot_token"])
            line("WARN", "Telegram", f"your chat id is {chat}, paste it into config/notify.yaml" if chat
                 else "token set, now send any message to your bot and run this again")
        else:
            line("PASS" if tg.get("bot_token") else "WARN", "Telegram", "set up" if tg.get("bot_token") else "not set up (optional, see config/notify.yaml)")
        if args.popup:
            ok = notify.windows_popup("Job search test", "If you can read this, pop-up alerts work.",
                                      "https://web3.career", None)
            line("PASS" if ok else "FAIL", "Test pop-up sent", "")
            if tg.get("bot_token") and tg.get("chat_id"):
                ok = notify.telegram(ncfg, "Job search test. Telegram alerts work.")
                line("PASS" if ok else "FAIL", "Test Telegram message", "")

    print("\nJob sites (tiny test search each, runs in parallel)")
    profile = smoke_profile(pipeline.load_profile())
    wanted = {s.strip().lower() for s in args.only.split(",")} if args.only else None
    cfgs = [smoke_cfg(c) for c in pipeline.load_sources(wanted)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: check_source(c, profile), cfgs))
    for name, verdict, n, secs, detail in results:
        line(verdict, f"{name}", f"{n:>4} jobs {secs:5.0f}s  {detail}")
        fails += verdict == "FAIL"
    print(f"\n{'All good.' if not fails else f'{fails} problem(s) above.'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
