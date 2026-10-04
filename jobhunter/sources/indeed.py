"""Indeed (added 2026-09-25) through the python-jobspy library, which reads Indeed's own mobile API.

Plain requests to in.indeed.com get a 403 bot page, but jobspy returned 30 India jobs with full
descriptions in about 5 s. Indeed's keyword matching is loose, so scoring filters as usual.

Config:
  searches       search terms (default blockchain, cryptocurrency, crypto exchange, web3)
  locations      [{location, country}] (default India)
  results        per search (default 40)
  hours_old      only jobs newer than this (default 72; the full run uses max_age_days)
"""
from __future__ import annotations

import logging

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, to_date


def _clean(value) -> str:
    """pandas gives NaN (a float that is not equal to itself) for missing cells."""
    return "" if value is None or value != value else str(value).strip()


_STATES = {"AP": "Andhra Pradesh", "AS": "Assam", "BR": "Bihar", "CH": "Chandigarh", "CT": "Chhattisgarh",
           "DL": "Delhi", "GA": "Goa", "GJ": "Gujarat", "HR": "Haryana", "HP": "Himachal Pradesh",
           "JK": "Jammu and Kashmir", "JH": "Jharkhand", "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh",
           "MH": "Maharashtra", "OR": "Odisha", "OD": "Odisha", "PB": "Punjab", "RJ": "Rajasthan", "TN": "Tamil Nadu",
           "TG": "Telangana", "TS": "Telangana", "UP": "Uttar Pradesh", "UT": "Uttarakhand", "UK": "Uttarakhand",
           "WB": "West Bengal"}


def _location(value) -> str:
    """Indeed India writes "Chennai, TN, IN" or just "TN, IN". "IN" alone reads as a foreign place to
    scoring, so every Indeed job was capped as abroad on-site (found 2026-09-25)."""
    parts = [p.strip() for p in _clean(value).split(",") if p.strip()]
    if parts and parts[-1] == "IN":
        parts[-1] = "India"
        if len(parts) >= 2 and parts[-2] in _STATES:
            parts[-2] = _STATES[parts[-2]]
    return ", ".join(parts)


def fetch(cfg, profile, log):
    try:
        from jobspy import scrape_jobs
    except ImportError as e:
        raise RuntimeError("python-jobspy is not installed (run setup.bat)") from e
    logging.getLogger("JobSpy").setLevel(logging.CRITICAL)
    jobs, failed = [], 0
    searches = cfg.get("searches") or ["blockchain", "cryptocurrency", "crypto exchange", "web3"]
    locations = cfg.get("locations") or [{"location": "India", "country": "India"}]
    for loc in locations:
        for term in searches:
            try:
                df = scrape_jobs(site_name=["indeed"], search_term=term, location=loc["location"],
                                 country_indeed=loc.get("country", "India"), results_wanted=cfg.get("results", 40),
                                 hours_old=cfg.get("hours_old", 72), verbose=0)
            except Exception as e:
                failed += 1
                log(f"WARNING '{term}' @ {loc['location']} failed: {e!r}"[:180])
                continue
            n = 0
            for _, r in df.iterrows():
                title, url = str(r.get("title") or ""), str(r.get("job_url") or "")
                if not title or not url:
                    continue
                location = _location(r.get("location"))
                remote = bool(r.get("is_remote")) if r.get("is_remote") == r.get("is_remote") else False
                lo, hi = r.get("min_amount"), r.get("max_amount")
                salary = (f"{r.get('currency') or ''} {lo:,.0f}-{hi:,.0f} {r.get('interval') or ''}".strip()
                          if lo == lo and hi == hi and lo and hi else "")
                desc = str(r.get("description") or "")
                jobs.append(Job(source=cfg["name"], title=title, url=url, company=_clean(r.get("company")),
                                location=("Remote, " + location) if remote else location,
                                work_mode="Remote" if remote else detect_work_mode(location, desc[:500]),
                                posted=to_date(r.get("date_posted")), salary=salary, description=desc[:6000]))
                n += 1
            log(f"'{term}' @ {loc['location']} → {n}")
    if failed and not jobs:
        raise RuntimeError("every Indeed search failed")
    return jobs
