"""JobStash (jobstash.xyz), a large crypto job aggregator with a public JSON API (added 2026-09-25).

middleware.jobstash.xyz/jobs/list takes `query`, `publicationDate` (today, this-week, past-2-weeks…)
and page/limit. In 2026 it also indexes plenty of non-crypto jobs (AI labs, hardware), so only posts
from organisations JobStash links to a crypto project, or whose text mentions a web3 word, are kept.

Some posts are "protected" (no direct apply URL for logged-out visitors); their JobStash page is used.

Config:
  queries           search words, each run separately (default crypto, blockchain, web3…)
  publication_date  JobStash window (default past-2-weeks; the watcher can use today)
  pages             pages of 100 per query (default 3)
"""
from __future__ import annotations

from jobhunter.models import Job
from jobhunter.scoring import _hits
from jobhunter.util import detect_work_mode, http_client, to_date

API = "https://middleware.jobstash.xyz/jobs/list"
_MODES = {"REMOTE": "Remote", "HYBRID": "Hybrid", "ONSITE": "Onsite"}


def _text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


def fetch(cfg, profile, log):
    web3_terms = profile["scoring"]["web3_terms"]
    queries = cfg.get("queries") or ["crypto", "blockchain", "web3", "defi", "stablecoin", "digital assets", "onchain"]
    seen, jobs, failed = set(), [], 0
    with http_client(log=log) as client:
        for q in queries:
            kept = 0
            for page in range(1, cfg.get("pages", 3) + 1):
                try:
                    # newest first, so one page of a week always holds the latest posts. "today" is a UTC day:
                    # the 11:15 IST check on 2026-09-26 got 0 jobs because the UTC day had just begun.
                    resp = client.get(API, params={"page": page, "limit": 100, "query": q,
                                                   "orderBy": "publicationDate", "order": "desc",
                                                   "publicationDate": cfg.get("publication_date", "past-2-weeks")})
                    data = resp.json()
                except Exception as e:
                    failed += 1
                    log(f"WARNING '{q}' page {page} failed ({type(e).__name__})")
                    break
                rows = data.get("data") or []
                for j in rows:
                    if j.get("id") in seen:
                        continue
                    seen.add(j.get("id"))
                    org = j.get("organization") or {}
                    tags = " ".join(t.get("name", "") for t in j.get("tags") or [])
                    text = " ".join([_text(j.get("summary")), _text(j.get("description")),
                                     _text(j.get("requirements")), _text(j.get("responsibilities")), tags])
                    crypto = bool(org.get("projects")) or bool(_hits(f"{j.get('title', '')} {text}".lower(), web3_terms))
                    if not crypto:
                        continue
                    url = j.get("url") or f"https://jobstash.xyz/jobs/{j.get('shortUUID')}/details"
                    location = j.get("location") or ""
                    mode = _MODES.get(str(j.get("locationType") or "").upper(), "")
                    if mode == "Remote" and "remote" not in location.lower():
                        location = f"Remote ({location})" if location else "Remote"
                    lo, hi = j.get("minimumSalary"), j.get("maximumSalary")
                    salary = f"{j.get('salaryCurrency') or 'USD'} {lo:,.0f}-{hi:,.0f}" if lo and hi else ""
                    if j.get("paysInCrypto"):
                        salary = (salary + " (pays in crypto)").strip()
                    jobs.append(Job(
                        source=cfg["name"], title=j.get("title", ""), url=url, company=org.get("name", ""),
                        location=location, work_mode=mode or detect_work_mode(location),
                        posted=to_date(j.get("timestamp")), salary=salary,
                        # full-time contractor roles (Bitfinex TM Analyst) are jobs, part-time ones are gigs
                        kind="freelance" if str(j.get("commitment") or "").upper() in ("PART_TIME", "PARTTIME") else "job",
                        description=f"{text} {'web3' if org.get('projects') else ''}"[:6000]))
                    kept += 1
                if len(rows) < 100:
                    break
            log(f"'{q}' → {kept} crypto jobs")
    if failed and not jobs:
        raise RuntimeError("every JobStash request failed")
    return jobs
