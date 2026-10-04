"""One search pass, shared by the full run (main.py) and the 24x7 watcher (watch.py). Added 2026-09-25.

fetch the given sources in parallel → retry a failed source once (full run) → score and merge
duplicates → remember per-source health and schedule → open apply pages of good jobs (verify) →
pick or build the CV for every row (cv) → write the workbook → alert about new jobs (notify).
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from jobhunter import excel, sources
from jobhunter.scoring import is_freelance, score, score_freelance
from jobhunter.store import SeenStore

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "Jobs.xlsx"
DB = ROOT / "data" / "seen_jobs.sqlite"
LAST_FULL = ROOT / "data" / "last_full_run.txt"     # when every source last ran with full settings
WARNING_WORDS = ("warning", "blocked", "rate-limited", "failed", "stopping")
DEFAULT_EVERY = {"ats": 30, "rss": 20, "html": 60, "telegram": 30, "superteam": 60, "remote_boards": 60,
                 "linkedin": 60, "naukri": 240, "naukrigulf": 480, "apna": 360, "vc_boards": 180,
                 "jobstash": 60, "remote_apis": 60, "indeed": 180, "india_boards": 240, "hn_hiring": 720,
                 "freelancer": 60}


def load_profile(days: int | None = None) -> dict:
    profile = yaml.safe_load((ROOT / "config" / "profile.yaml").read_text(encoding="utf-8"))
    if days:
        profile["max_age_days"] = days
    return profile


def load_sources(only: set[str] | None = None) -> list[dict]:
    cfgs = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    return [s for s in cfgs if s.get("enabled", True) and (only is None or s["name"].lower() in only)]


def every_minutes(cfg: dict) -> int:
    return int(cfg.get("every_minutes") or DEFAULT_EVERY.get(cfg.get("type"), 120))


def run_source(cfg, profile, log=print, retry_after: float = 0):
    """Fetch one source. A source that fails outright is retried once after `retry_after` seconds."""
    attempts = 2 if retry_after else 1
    for attempt in range(1, attempts + 1):
        started, warnings = time.time(), []

        def say(msg, _w=warnings):
            log(f"  [{cfg['name']}] {msg}")
            if any(w in msg.lower() for w in WARNING_WORDS):
                _w.append(msg)

        try:
            jobs = sources.load(cfg).fetch(cfg, profile, say)
            status = f"ok in {time.time() - started:.0f}s"
            if warnings:  # partial results: show why in the Run Log
                status += f" — {len(warnings)} warning(s): " + " / ".join(warnings[-3:])
            return cfg, jobs, status[:500]
        except Exception as e:
            status = f"FAILED: {e!r}"[:500]
            if attempt < attempts:
                log(f"  [{cfg['name']}] {status[:160]}, trying the whole source again in {retry_after:.0f}s")
                time.sleep(retry_after)
    return cfg, [], status


def fetch_all(cfgs, profile, log=print, retry_after: float = 0):
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(len(cfgs), 12))) as pool:
        futures = [pool.submit(run_source, c, profile, log, retry_after) for c in cfgs]
        for fut in as_completed(futures):
            cfg, jobs, status = fut.result()
            log(f"✔ {cfg['name']}: {len(jobs)} jobs ({status})")
            results.append((cfg, jobs, status))
    return results


def fill_saved_texts(results, store) -> int:
    """VC portfolio listings carry no description. The link check saves each good one's apply page text,
    so it is used here and scoring can tell a crypto job from a fintech one (Veem, 2026-09-26)."""
    n = 0
    for _, jobs, _ in results:
        for job in jobs:
            if job.web3_hint and not job.description:
                job.description = store.text(job.key)
                n += bool(job.description)
    return n


def score_and_merge(results, profile, today: date):
    sc, min_score = profile["scoring"], profile.get("min_score", 25)
    fsc = profile["freelance_scoring"]
    bands, fl_words = profile.get("priority_bands"), profile.get("freelance_words", [])
    oldest = today - timedelta(days=profile.get("max_age_days", 14))
    best, dropped, per_source = {}, set(), {}
    for cfg, jobs, status in results:
        kept = 0
        src_oldest = today - timedelta(days=cfg["max_age_days"]) if cfg.get("max_age_days") else oldest
        for job in jobs:
            if not job.title or not job.url or (job.posted and job.posted < src_oldest and not cfg.get("type") == "ats"):
                continue
            if is_freelance(job, fl_words):
                job.kind = "freelance"
                score_freelance(job, fsc, sc, today, bands)
                if job.score < fsc.get("min_score", 30) or "⛔" in job.flags or "Country-locked" in job.flags:
                    dropped.add(job.key)
                    continue
            else:
                score(job, sc, today, bands)
                if job.score < min_score:
                    dropped.add(job.key)
                    continue
            kept += 1
            other = best.get(job.key)
            if other is None:
                best[job.key] = job
            else:  # same job on two sites: keep the better-informed copy, remember the other site.
                # A listing without a description can't be checked for experience or skill gaps, so
                # its score is optimistic; the copy with the real job text wins, then the higher score.
                rank = lambda j: (len(j.description) > 200, j.score)
                keep, drop = (job, other) if rank(job) > rank(other) else (other, job)
                keep.also_on = sorted(set(keep.also_on + [drop.source] + drop.also_on) - {keep.source})
                best[job.key] = keep
        per_source[cfg["name"]] = [len(jobs), kept, status]
    return best, dropped, per_source


def health_rows(store: SeenStore, cfgs_all: list[dict]) -> list[list]:
    every = {c["name"]: every_minutes(c) for c in cfgs_all}
    rows = []
    for s in store.all_source_states():
        if s["name"] not in every:
            continue
        fmt = lambda v: (v or "").replace("T", " ")[:16]
        rows.append([s["name"], f"{every[s['name']]} min", fmt(s.get("last_ok")), fmt(s.get("last_try")),
                     s.get("last_status") or "", s.get("last_count"), store.usual_count(s["name"]) or "",
                     s.get("fails") or 0, fmt(s.get("next_due"))])
    return rows


def internet_ok() -> bool:
    import httpx
    for url in ("https://www.google.com/generate_204", "https://1.1.1.1"):
        try:
            httpx.head(url, timeout=8)
            return True
        except Exception:
            pass
    return False


def usual_key(cfg: dict) -> str:
    """Quick watcher checks (LinkedIn newest posts only, JobStash today only) return far fewer jobs than
    full searches, so each kind is compared only with its own history. Mixing them made the watcher
    call LinkedIn and JobStash "probably blocked" all night on 2026-09-25 and send false alerts."""
    return f"{cfg['name']} [quick]" if cfg.get("_quick") else cfg["name"]


STATE = ROOT / "data" / "state.json"
STATE_FIELDS = ("Key", "Status", "Priority", "Score", "Title", "Company", "Location", "Work mode", "Salary", "Experience",
                "Deadline", "Why it matched", "Flags", "Apply link", "CV", "Cover letter", "Link check", "Source", "Notes",
                "Referral message", "Follow-up message", "Days since", "Status date", "First seen", "_cv_link",
                "_cl_link", "_referrer", "_kind")


def _slim(row: dict) -> dict:
    return {k: (str(row[k]) if row.get(k) is not None else "") for k in STATE_FIELDS if k in row}


ROLE_KINDS = [  # first match wins, so "Quality Analyst - AML" counts as compliance
    ("Compliance", ["kyc", "kyb", "aml", "anti-money*", "compliance", "fraud*", "risk", "sanctions", "transaction monitoring",
                    "investigat*", "forensic*", "financial crime*", "surveillance", "intelligence", "threat*", "osint",
                    "soc", "security", "due diligence", "mlro", "sar"]),
    ("QA testing", ["qa", "quality", "test*", "tester", "sdet"]),
    ("Support ops", ["support", "operations", "ops", "customer*", "success", "onboarding", "service", "settlement*",
                     "treasury", "help desk", "helpdesk", "account manager"]),
    ("Community", ["community", "moderator*", "ambassador*", "content", "social", "writer", "kol", "marketing", "brand",
                   "devrel", "developer relations", "growth"]),
    ("Research", ["research*", "analyst", "analytics", "market*", "token*", "investment*", "strategy", "data"]),
    ("Engineering", ["engineer*", "developer*", "devops", "sre", "solidity", "smart contract*", "architect", "programmer"]),
]


def role_kind(title: str) -> str:
    from jobhunter.scoring import _hits
    t = str(title or "").lower()
    return next((name for name, words in ROLE_KINDS if _hits(t, words)), "Other")


def stats(jobs: list[dict], gigs: list[dict], lists: dict) -> dict:
    """Counts for the Telegram Stats card: per kind of role, jobs to do, applied, at interview and skipped."""
    queue = set(lists.get("queue") or [])
    table = {name: {"name": name, "todo": 0, "applied": 0, "interview": 0, "skipped": 0} for name, _ in ROLE_KINDS}
    table["Other"] = {"name": "Other", "todo": 0, "applied": 0, "interview": 0, "skipped": 0}
    where = {"remote": 0, "india": 0, "abroad": 0}
    from jobhunter.excel import is_remote
    for r in jobs:
        status = str(r.get("Status") or "New")
        row = table[role_kind(r.get("Title"))]
        if r["Key"] in queue:
            row["todo"] += 1
            loc = str(r.get("Location") or "").lower()
            where["remote" if is_remote(r) else "india" if any(c in loc for c in INDIA_PLACES) else "abroad"] += 1
        elif status in ("Applied", "Offer"):
            row["applied"] += 1
        elif status == "Interview":
            row["interview"] += 1
            row["applied"] += 1
        elif status in ("Skip", "Not relevant") and (r.get("Score") or 0) >= 55:
            row["skipped"] += 1
    rows = [r for r in table.values() if any(r[k] for k in ("todo", "applied", "interview", "skipped"))]
    total = {k: sum(r[k] for r in rows) for k in ("todo", "applied", "interview", "skipped")}
    return {"rows": rows, "total": total, "where": where, "new_today": len(lists.get("new") or []),
            "gigs": sum(1 for g in gigs if str(g.get("Status") or "New") == "New" and (g.get("Score") or 0) >= 55)}


INDIA_PLACES = ("india", "lucknow", "noida", "delhi", "gurugram", "gurgaon", "bengaluru", "bangalore", "hyderabad",
                "pune", "mumbai", "chennai", "kolkata", "ahmedabad", "jaipur", "indore", "chandigarh", "gandhinagar",
                "kochi", "mohali", "nashik", "kanpur")


def write_state(result) -> None:
    """What the Telegram bot shows: the plan, every row of the sheet and ready-made lists (one per tab), as
    JSON. The bot never opens the workbook, so it works while the workbook is open or being written."""
    import json as _json
    from jobhunter.excel import _queue_sorted, _sorted, follow_ups, is_remote, queue_ok, remote_ok
    plan = dict(result.plan or {})
    for key in ("jobs", "followups", "queue"):
        plan[key] = [r.get("Key") for r in plan.get(key) or []]
    if plan.get("gig"):
        plan["gig"] = plan["gig"].get("Key")
    everything = [r for r in result.rows.values() if r.get("Key")]
    jobs = [r for r in everything if r.get("_kind") != "freelance"]
    gigs = [r for r in everything if r.get("_kind") == "freelance"]
    today = date.today().isoformat()
    acted = lambda r: str(r.get("Status") or "New") in ("Applied", "Interview", "Offer", "Rejected")
    keys = lambda rows: [r["Key"] for r in rows]
    lists = {
        "queue": keys(_queue_sorted([r for r in jobs if queue_ok(r)])),
        "remote": keys(_sorted([r for r in jobs if remote_ok(r) and str(r.get("Status") or "New") == "New"])),
        "new": keys(sorted([r for r in jobs if str(r.get("First seen") or "")[:10] == today], key=lambda r: -(r.get("Score") or 0))),
        "gigs": keys(_sorted([r for r in gigs if str(r.get("Status") or "New") == "New"])),
        "applied": keys(sorted([r for r in everything if acted(r)], key=lambda r: str(r.get("Status date") or r.get("First seen") or ""),
                               reverse=True)),
        "followups": keys(follow_ups(everything, date.today())),
        "india": keys(_sorted([r for r in jobs if str(r.get("Status") or "New") == "New" and not is_remote(r)
                               and any(c in str(r.get("Location") or "").lower() for c in INDIA_PLACES)
                               and (r.get("Score") or 0) >= 55])),
        "all": keys(_sorted(jobs)),
    }
    rows = {r["Key"]: _slim(r) for r in everything}
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(_json.dumps({"generated": datetime.now().isoformat(timespec="seconds"), "plan": plan, "rows": rows,
                                "lists": lists, "stats": stats(jobs, gigs, lists)}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)


def sync(log=print) -> str | None:
    """Rewrite the workbook without fetching anything, so Telegram taps and the Today tab show up at once.
    Skipped (returns None) when a check is running, which applies the taps itself."""
    from jobhunter.lock import RunLock
    lock = RunLock(ROOT / "data" / "run.lock")
    if not lock.acquire(wait_seconds=0):
        return None
    try:
        profile = load_profile()
        sc, bands = profile["scoring"], profile.get("priority_bands")
        store = SeenStore(DB)
        states = store.all_source_states()
        earn = yaml.safe_load((ROOT / "config" / "earn_platforms.yaml").read_text(encoding="utf-8"))
        result = excel.save(OUTPUT, [], {}, date.today(), [], bands, earn_platforms=earn, scoring=sc,
                            source_last_ok={s["name"]: s.get("last_ok") for s in states if s.get("last_ok")},
                            health_rows=health_rows(store, load_sources()), urls=store.urls(),
                            actions=store.pending_actions())
        if result.actions_saved:
            store.mark_actions_saved(result.actions_saved)
        for r in result.rows.values():
            if str(r.get("Status") or "") == "Not relevant":
                store.add_feedback(r["Key"], str(r.get("Title") or ""), str(r.get("Company") or ""))
        store.close()
        write_state(result)
        log(f"workbook updated ({result.path.name})")
        return str(result.path)
    finally:
        lock.release()


def apply_feedback(best: dict, store, bands) -> int:
    """Jobs whose title is nearly the same as one you marked Not relevant lose 25 points and say why."""
    from jobhunter.excel import _title_words
    marked = [(set(_title_words(t)), t, k) for k, t, _ in store.feedback()]
    if not marked:
        return 0
    n = 0
    for key, job in best.items():
        words = set(_title_words(job.title))
        for mw, title, mkey in marked:
            if key != mkey and words and mw and len(words & mw) / len(words | mw) >= 0.75:
                job.score = max(0, job.score - 25)
                job.flags = "; ".join(filter(None, [f"Similar to a job you marked Not relevant ({title[:40]})", job.flags]))
                job.priority = next((b["label"] for b in bands or [] if job.score >= b["min"]), job.priority)
                n += 1
                break
    return n


def run(cfgs: list[dict], profile: dict, mode: str = "full", log=print, notify_new: bool = True,
        full_names: set | None = None, full_pass: bool = False) -> dict:
    """mode: "full" (run_jobs.bat and the daily morning pass: full settings, retries, big link-check budget)
    or "watch" (due sources only, with their quick `watch:` settings, except those in full_names, which
    have been offline long enough to need a full catch-up)."""
    watch = mode == "watch"
    full_names = full_names or set()
    if watch:
        cfgs = [c if c["name"] in full_names or not c.get("watch") else {**c, **c["watch"], "_quick": True}
                for c in cfgs]
    today, now = date.today(), datetime.now()
    run_at = now.strftime("%Y-%m-%d %H:%M")
    log(f"{'Watcher check' if watch else 'Full search'} of {len(cfgs)} source(s): {', '.join(c['name'] for c in cfgs)}"
        + (f"\n(full catch-up after a long gap for {', '.join(sorted(full_names))})" if watch and full_names else "") + "\n")

    results = fetch_all(cfgs, profile, log, retry_after=0 if watch else 75)
    store = SeenStore(DB)
    fill_saved_texts(results, store)
    best, dropped, per_source = score_and_merge(results, profile, today)
    # A Wi-Fi drop in the middle of a check makes sources fail through no fault of their own. Those are
    # simply retried at the next check, without counting as failures or triggering back-off.
    offline = any(status.startswith("FAILED") for _, _, status in results) and not internet_ok()
    if offline:
        log("the internet dropped during this check, failed sources will be retried at the next check")

    store.save_texts((k, j.description) for k, j in best.items() if len(j.description or "") > 150)
    pushed = apply_feedback(best, store, profile.get("priority_bands"))
    if pushed:
        log(f"pushed down {pushed} job(s) similar to ones you marked Not relevant")
    first_seen = {k: store.first_seen(k) or today.isoformat() for k in best}
    new_keys = {k for k, d in first_seen.items() if d == today.isoformat()}
    found_at = {k: (store.found_at(k) or (now.strftime("%Y-%m-%d %H:%M") if store.first_seen(k) is None else ""))
                for k in best}
    log_rows, alerts = [], []
    for cfg, jobs, status in results:
        name = cfg["name"]
        fetched, kept, status = per_source[name]
        usual = store.usual_count(usual_key(cfg))
        ok = not status.startswith("FAILED")
        if ok and usual and fetched < usual * 0.4 and not offline:  # a silent block looks like "ok" but with far fewer jobs
            status += f" — ⚠ only {fetched} jobs (usually ~{usual}): probably blocked or site changed"
            ok = False
        if not ok or "warning" in status:
            alerts.append(f"{name}: {status}")
        new = sum(1 for k in new_keys if best[k].source.split(":")[0] == name.split(":")[0])
        log_rows.append([run_at, name, fetched, kept, new, status + (" (quick check)" if cfg.get("_quick") else "")])
        if fetched and ok and "warning" not in status:
            store.record_run(run_at, usual_key(cfg), fetched)  # only healthy runs define "usual"
        if offline and not ok:
            store.postpone(name, 15, f"offline during check: {status}"[:300], now)
        else:
            store.record_source(name, ok, status, fetched, every_minutes(cfg), now)

    sc, bands = profile["scoring"], profile.get("priority_bands")
    all_cfgs = load_sources()
    states = store.all_source_states()
    last_ok = {s["name"]: s.get("last_ok") for s in states if s.get("last_ok")}

    def enrich(rows):
        from jobhunter import cv, verify
        try:
            verify.apply(rows, store, sc, bands, log, budget=25 if watch else 80,
                         hint_sources=tuple(c["name"] for c in all_cfgs if c.get("web3_hint")))
        except Exception as e:  # a link check problem must never stop the save
            log(f"link check skipped: {e!r}"[:200])
        try:
            cv.assign(rows, store, sc, log, build=True, max_builds=20 if watch else 150)
        except Exception as e:
            log(f"CV step skipped: {e!r}"[:200])
        try:
            from jobhunter import cover
            cover.assign(rows, store, sc, log, max_builds=25 if watch else 150)
        except Exception as e:
            log(f"cover letter step skipped: {e!r}"[:200])

    earn = yaml.safe_load((ROOT / "config" / "earn_platforms.yaml").read_text(encoding="utf-8"))
    result = excel.save(OUTPUT, list(best.values()), first_seen, today, log_rows, bands,
                        earn_platforms=earn, dropped_keys=dropped - set(best), scoring=sc, found_at=found_at,
                        source_last_ok=last_ok, health_rows=health_rows(store, all_cfgs), enrich=enrich,
                        urls={**store.urls(), **{k: j.url for k, j in best.items()}},
                        actions=store.pending_actions())
    for job in best.values():   # side files are merged back later, so their jobs count as seen too
        store.upsert(job, today, found_at.get(job.key) or None)
    if result.actions_saved:
        store.mark_actions_saved(result.actions_saved)
    for r in result.rows.values():   # "Not relevant" teaches the scoring what to push down next time
        if str(r.get("Status") or "") == "Not relevant":
            store.add_feedback(r["Key"], str(r.get("Title") or ""), str(r.get("Company") or ""))
    store.commit()
    write_state(result)

    sent = 0
    if notify_new:
        from jobhunter import notify, tgbot
        try:
            sent = notify.new_jobs(result.rows, new_keys, store, log)
            notify.source_problems(store.all_source_states(), store, log)
            tgbot.daily_messages(store, log)
        except Exception as e:
            log(f"alerts skipped: {e!r}"[:200])
    store.close()

    gigs = [j for j in best.values() if j.kind == "freelance"]
    log(f"\n{len(best) - len(gigs)} relevant jobs + {len(gigs)} freelance gigs from this check, {len(new_keys)} new today.")
    for label, items in (("Top new jobs", [best[k] for k in new_keys if best[k].kind == "job"]),
                         ("Top new freelance gigs", [best[k] for k in new_keys if best[k].kind == "freelance"])):
        top = sorted(items, key=lambda j: -j.score)[:8]
        if top:
            log(f"{label}:")
            for j in top:
                pay = f" [{j.salary[:18]}]" if j.salary else ""
                log(f"  {j.score:>3}  {j.title[:55]:<55} {j.company[:20]:<20}{pay} [{j.source}]")
    if alerts:
        log("\nPROBLEMS THIS RUN (details in the Run Log and Health tabs):")
        for a in alerts:
            log(f"  ⚠ {a[:220]}")
    log(f"\nSaved: {result.path}")
    if result.side_files_merged:
        log(f"Merged {len(result.side_files_merged)} side file(s) saved while the workbook was open: "
            f"{', '.join(result.side_files_merged)}")
    if result.path != OUTPUT:
        log("NOTE: Jobs.xlsx was open, so results went to the file above.\n"
            "      They are merged into Jobs.xlsx automatically on the next check after you close it.")
    summary = {"at": now.isoformat(timespec="seconds"), "mode": mode, "sources": [c["name"] for c in cfgs],
               "jobs": len(best), "new_today": len(new_keys), "alerted": sent, "saved_to": str(result.path),
               "problems": alerts}
    (ROOT / "data" / "last_run.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if full_pass:   # the watcher does the daily morning pass only if none has happened today
        LAST_FULL.write_text(now.isoformat(timespec="seconds"), encoding="utf-8")
    return summary
