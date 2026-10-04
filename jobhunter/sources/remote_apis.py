"""Remote-job boards whose APIs say WHERE a remote job can be done from (added 2026-09-25).

Himalayas (himalayas.app/jobs/api/search) lists `locationRestrictions` (countries) and
`timezoneRestrictions` (UTC offsets). An empty list means worldwide. India is UTC+5.5.
Jobicy (jobicy.com/api/v2/remote-jobs?tag=…) gives `jobGeo` ("Anywhere", "APAC", "USA"…).

That eligibility goes into the Location field ("Remote (Worldwide)", "Remote (USA)"), so the normal
region rules in scoring decide whether you can apply from India, and the Remote Jobs tab can trust it.

Config:
  himalayas_queries  search words (default crypto, blockchain, web3, defi…)
  jobicy_tags        tags (default crypto, blockchain, web3)
"""
from __future__ import annotations

from jobhunter.models import Job
from jobhunter.util import html_to_text, http_client, to_date

IST = 5.5


def _himalayas_location(countries, zones) -> str:
    countries = [c for c in countries or [] if c]
    zones = [z for z in zones or [] if z is not None]
    if not countries and (not zones or len(zones) > 20):
        return "Remote (Worldwide)"
    if any(c.lower() == "india" for c in countries):
        return "Remote (India)"
    if not countries and IST in zones:
        return "Remote (Asia time zones)"     # "asia" counts as open to India in scoring
    return f"Remote ({', '.join(countries[:4]) or 'UTC ' + ', '.join(str(z) for z in zones[:4])} only)"


def _himalayas(client, cfg, log):
    out, seen = [], set()
    for q in cfg.get("himalayas_queries") or ["crypto", "blockchain", "web3", "defi", "stablecoin", "bitcoin", "ethereum"]:
        data = client.get("https://himalayas.app/jobs/api/search", params={"q": q, "limit": 100}).json()
        for j in data.get("jobs") or []:
            url = j.get("applicationLink") or j.get("guid")
            if not url or url in seen:
                continue
            seen.add(url)
            lo, hi = j.get("minSalary"), j.get("maxSalary")
            salary = f"{j.get('currency') or 'USD'} {lo:,}-{hi:,}" if lo and hi else ""
            # "Contractor" is usually a full-time remote role paid as a contractor, so it stays a job
            kind = "freelance" if str(j.get("employmentType") or "").lower() in ("part time", "part-time", "temporary") else "job"
            out.append(Job(source="", title=j.get("title", ""), url=url, company=j.get("companyName", ""),
                           location=_himalayas_location(j.get("locationRestrictions"), j.get("timezoneRestrictions")),
                           work_mode="Remote", posted=to_date(j.get("pubDate")), salary=salary,
                           description=html_to_text(j.get("description"))
                           + " " + " ".join(j.get("categories") or []), kind=kind))
    log(f"himalayas: {len(out)} jobs")
    return out


def _jobicy(client, cfg, log):
    out, seen = [], set()
    for tag in cfg.get("jobicy_tags") or ["crypto", "blockchain", "web3"]:
        data = client.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": tag}).json()
        for j in data.get("jobs") or []:
            if j.get("url") in seen:
                continue
            seen.add(j.get("url"))
            geo = (j.get("jobGeo") or "").strip()
            anywhere = geo.lower() in ("anywhere", "worldwide", "")
            location = "Remote (Worldwide)" if anywhere else (f"Remote ({geo})" if "apac" in geo.lower() or "asia" in geo.lower()
                                                               else f"Remote ({geo} only)")
            lo, hi = j.get("annualSalaryMin"), j.get("annualSalaryMax")
            salary = f"{j.get('salaryCurrency') or 'USD'} {lo}-{hi}" if lo and hi else ""
            types = " ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else str(j.get("jobType") or "")
            out.append(Job(source="", title=j.get("jobTitle", ""), url=j.get("url", ""), company=j.get("companyName", ""),
                           location=location, work_mode="Remote", posted=to_date(j.get("pubDate")), salary=salary,
                           description=html_to_text(j.get("jobDescription")) + f" {tag}",
                           kind="freelance" if "part" in types.lower() else "job"))
    log(f"jobicy: {len(out)} jobs")
    return out


BOARDS = {"himalayas": _himalayas, "jobicy": _jobicy}


def fetch(cfg, profile, log):
    jobs, failed = [], 0
    boards = cfg.get("boards") or list(BOARDS)
    with http_client(log=log) as client:
        for board in boards:
            try:
                found = BOARDS[board](client, cfg, log)
            except Exception as e:
                failed += 1
                log(f"WARNING {board} failed: {e!r}"[:200])
                continue
            for j in found:
                j.source = f"{cfg['name']}: {board}"
            jobs.extend(found)
    if failed == len(boards):
        raise RuntimeError("every remote API failed")
    return jobs
