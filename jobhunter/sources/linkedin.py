"""LinkedIn public job search — the logged-out "guest" endpoints LinkedIn serves to anyone.

Never uses your LinkedIn account. Other modes (google_index, session) are deliberately
not built yet — see handoff.md, "LinkedIn — to revisit later".

Searches come from profile.yaml → linkedin_searches (LinkedIn supports OR / AND / "quotes").
For jobs whose title doesn't say crypto/web3, the job description is fetched too (capped by
max_descriptions) so scoring can tell a crypto-exchange support job from a bank's.

Descriptions are cached in data/linkedin_details.sqlite, and the 14-day backfill pass runs once
per backfill_every_hours (2026-09-25): each run was re-downloading the same ~120 descriptions and
~84 backfill pages, which made LinkedIn 920 of a 15-minute run.
"""
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from jobhunter.models import Job
from jobhunter.scoring import _hits
from jobhunter.util import detect_work_mode, http_client, to_date

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
CACHE = Path(__file__).resolve().parents[2] / "data" / "linkedin_details.sqlite"


def _cache():
    db = sqlite3.connect(CACHE)
    db.execute("CREATE TABLE IF NOT EXISTS details (job_id TEXT PRIMARY KEY, description TEXT, experience TEXT, fetched TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    db.execute("DELETE FROM details WHERE fetched < ?", ((datetime.now() - timedelta(days=45)).isoformat(),))
    return db


def _text(card, sel):
    node = card.select_one(sel)
    return node.get_text(" ", strip=True) if node else ""


def _pause(cfg):
    time.sleep(cfg.get("delay_seconds", 2) * random.uniform(0.7, 1.3))


def _get(client, url, cfg, log, **params):
    """GET with polite back-off. LinkedIn answers 429 (too many requests) when a network asks too fast;
    waiting a minute or two usually clears it. Returns None if it's still refusing after the retries."""
    for attempt, wait in enumerate([0] + list(cfg.get("backoff_seconds", [60, 180]))):
        if wait:
            log(f"rate-limited (429) — waiting {wait}s before retry {attempt}")
            time.sleep(wait)
        try:
            resp = client.get(url, params=params or None)
        except Exception as e:  # network hiccup: treat like a refusal and retry
            log(f"request error {e!r}"[:120])
            continue
        if resp.status_code != 429:
            return resp
    return None


def fetch(cfg, profile, log):
    if cfg.get("mode", "guest") != "guest":
        raise NotImplementedError(f"LinkedIn mode '{cfg['mode']}' is not built yet — use mode: guest")
    backfill_seconds = int(profile.get("max_age_days", 14)) * 86400
    # Two passes per search × location. LinkedIn caps what it returns, and ranks by relevance across
    # the whole window, so a job posted this morning can sit below two weeks of older listings and
    # never make the top results (found 2026-09-19: a 6-hour-old "Investment Researcher – Web3" job
    # was missing from every search; a 24-hour window put it at position 8).
    passes = [
        ("fresh", {"f_TPR": f"r{cfg.get('fresh_window_hours', 24) * 3600}", "sortBy": "DD"},
         cfg.get("fresh_results_per_search", 60)),
        ("backfill", {"f_TPR": f"r{backfill_seconds}"}, cfg.get("results_per_search", 30)),
    ]
    db = _cache()
    last = (db.execute("SELECT v FROM meta WHERE k='backfill'").fetchone() or [""])[0]
    if last and datetime.now() - datetime.fromisoformat(last) < timedelta(hours=cfg.get("backfill_every_hours", 0)):
        passes = passes[:1]
        log(f"backfill pass skipped (last one {last[:16]}, runs every {cfg['backfill_every_hours']} h)")
    jobs: dict[str, Job] = {}

    with http_client(tries=3, retry_429=False) as client:  # 429 handled by _get
        for pass_name, window, limit in passes:
            for query in profile["linkedin_searches"]:
                for loc in profile.get("linkedin_locations", [{"location": "India"}]):
                    params = {"keywords": query, "location": loc["location"], **window}
                    if loc.get("remote"):
                        params["f_WT"] = "2"
                    found = 0
                    for start in range(0, limit, 10):
                        resp = _get(client, SEARCH, cfg, log, **params, start=start)
                        if resp is None:
                            log("WARNING: LinkedIn still rate-limiting after retries — stopped early; results so far are kept")
                            return list(jobs.values())
                        if resp.status_code != 200:
                            break
                        cards = BeautifulSoup(resp.text, "lxml").select("div.base-card")
                        for card in cards:
                            link = card.select_one("a.base-card__full-link") or card.select_one("a")
                            urn = card.get("data-entity-urn", "")
                            job_id = urn.rsplit(":", 1)[-1] if urn else ""
                            if not link or not job_id or job_id in jobs:
                                continue
                            location = _text(card, ".job-search-card__location")
                            date_node = card.select_one("time")
                            jobs[job_id] = Job(
                                source=cfg["name"], title=_text(card, ".base-search-card__title"),
                                url=f"https://www.linkedin.com/jobs/view/{job_id}",
                                company=_text(card, ".base-search-card__subtitle"), location=location,
                                work_mode="Remote" if loc.get("remote") else detect_work_mode(location),
                                posted=to_date(date_node.get("datetime") if date_node else None),
                                salary=_text(card, ".job-search-card__salary-info"),
                            )
                            found += 1
                        _pause(cfg)
                        if len(cards) < 10:
                            break
                    log(f"[{pass_name}] {query[:60]} @ {loc['location']}{' (remote)' if loc.get('remote') else ''} → {found} new")

            if pass_name == "backfill":
                db.execute("INSERT OR REPLACE INTO meta VALUES ('backfill', ?)", (datetime.now().isoformat(),))
                db.commit()

        # Descriptions only for on-target titles that don't say whether this is a crypto job.
        sc = profile["scoring"]
        tier_phrases = [p for tier in sc["title_tiers"] for p in tier["phrases"]]
        unclear = [(jid, j) for jid, j in jobs.items()
                   if not _hits(f"{j.title} {j.company}".lower(), sc["web3_terms"])
                   and _hits(j.title.lower(), tier_phrases)
                   and not _hits(j.title.lower(), sc.get("off_target_title_words", []))]
        todo = []
        for jid, job in unclear:
            row = db.execute("SELECT description, experience FROM details WHERE job_id=?", (jid,)).fetchone()
            if row:
                job.description, job.experience = row
                if not job.work_mode:
                    job.work_mode = detect_work_mode(job.location, job.description[:600])
            else:
                todo.append((jid, job))
        limit = cfg.get("max_descriptions", 120)
        log(f"{len(jobs)} jobs; {len(unclear) - len(todo)} of {len(unclear)} unclear-title descriptions cached, "
            f"fetching {min(limit, len(todo))}")
        for jid, job in todo[:limit]:
            resp = _get(client, POSTING.format(jid), cfg, log)
            if resp is None:
                log("WARNING: rate-limited while fetching descriptions — scoring the rest on title only")
                break
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                job.description = re.sub(r"\s+", " ", _text(soup, ".show-more-less-html__markup"))[:6000]
                crit = {_text(li, "h3"): _text(li, "span") for li in soup.select("li.description__job-criteria-item")}
                job.experience = crit.get("Seniority level", "")
                if not job.work_mode:
                    job.work_mode = detect_work_mode(job.location, job.description[:600])
                db.execute("INSERT OR REPLACE INTO details VALUES (?,?,?,?)",
                           (jid, job.description, job.experience, datetime.now().isoformat()))
                db.commit()
            _pause(cfg)
    db.close()
    return list(jobs.values())
