"""Crypto VC portfolio job boards (added 2026-09-25).

Crypto funds publish one job board covering every company they back. Two platforms run almost all
of them, and both have a public JSON search behind the page:

  Getro     jobs.solana.com, jobs.dragonfly.xyz, jobs.polychain.capital, …
            POST api.getro.com/api/v2/collections/<id>/search/jobs  (needs Accept: application/json,
            answers 406 without it). Newest first.
  Consider  jobs.panteracapital.com, jobs.hashed.com, jobs.shima.capital
            POST <host>/api-boards/search-jobs with the csrfToken printed in the board page
            (412 INVALID_CSRF without it).

Listings carry title, company, locations, work mode and date but no description, so scoring works
from the title, company and location. Most companies on these boards are crypto companies, but funds
also back fintechs (Veem, cross-border payments, Pantera), so a listing is only a web3 *hint*
(`Job.web3_hint`). The link check saves the apply page text, and job text without a web3 word
overrules the hint (scoring.score, 2026-09-26).

Config:
  getro:    { Board name: [host, collection_id] }
  consider: { Board name: [host, board_id] }
  pages:    pages of 100 per board (default 3). Paging stops early once posts are older than max_age_days.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, http_client, to_date

GETRO = "https://api.getro.com/api/v2/collections/{}/search/jobs"
_MODES = {"remote": "Remote", "hybrid": "Hybrid", "on_site": "Onsite", "onsite": "Onsite"}


def _getro(client, board, host, collection, pages, oldest, log):
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "Origin": f"https://{host}", "Referer": f"https://{host}/"}
    out = []
    for page in range(pages):
        resp = client.post(GETRO.format(collection), headers=headers,
                           json={"hits_per_page": 100, "page": page})  # camelCase hitsPerPage caps at 20
        if resp.status_code != 200:
            log(f"WARNING {board}: HTTP {resp.status_code} on page {page + 1}")
            break
        jobs = (resp.json().get("results") or {}).get("jobs") or []
        for j in jobs:
            posted = to_date(j.get("created_at"))
            if posted and posted < oldest:
                continue
            locations = j.get("locations") or j.get("searchable_locations") or []
            location = "; ".join(locations[:4]) if isinstance(locations, list) else str(locations)
            mode = _MODES.get(str(j.get("work_mode") or "").lower(), "")
            lo, hi = j.get("compensation_amount_min_cents"), j.get("compensation_amount_max_cents")
            salary = (f"{j.get('compensation_currency') or 'USD'} {lo // 100:,}-{hi // 100:,}"
                      if lo and hi and j.get("compensation_public") else "")
            out.append(Job(source="", title=j.get("title", ""), url=j.get("url", ""),
                           company=(j.get("organization") or {}).get("name", ""),
                           location=location or ("Remote" if mode == "Remote" else ""),
                           work_mode=mode or detect_work_mode(location), posted=posted, salary=salary))
        dates = [d for d in (to_date(j.get("created_at")) for j in jobs) if d]
        if len(jobs) < 100 or (dates and min(dates) < oldest):  # newest first: the rest is older
            break
    return out


def _consider(client, board, host, board_id, pages, oldest, log):
    page_html = client.get(f"https://{host}/jobs").text
    m = re.search(r'"csrfToken":"([^"]+)"', page_html)
    if not m:
        log(f"WARNING {board}: no csrf token on the board page (layout changed?)")
        return []
    headers = {"Accept": "application/json", "x-csrf-token": m.group(1),
               "Origin": f"https://{host}", "Referer": f"https://{host}/jobs"}
    out, meta = [], {"size": 100}
    for _ in range(pages):
        body = {"meta": meta, "board": {"id": board_id, "isParent": True},
                "query": {"promoteFeatured": False}, "grouped": False}
        resp = client.post(f"https://{host}/api-boards/search-jobs", json=body, headers=headers)
        if resp.status_code != 200:
            log(f"WARNING {board}: HTTP {resp.status_code}")
            break
        data = resp.json()
        jobs = data.get("jobs") or []
        for j in jobs:
            if (j.get("applicationWindow") or {}).get("status", "accepting") != "accepting":
                continue
            posted = to_date(j.get("timeStamp"))
            if posted and posted < oldest:
                continue
            locations = j.get("locations") or []
            location = "; ".join(locations[:4])
            remote = j.get("remote") in (True, "True", "true")
            if remote and "remote" not in location.lower():
                location = f"Remote ({location})" if location else "Remote"
            sal = j.get("salary") or {}
            salary = (f"{(sal.get('currency') or {}).get('value', 'USD') if isinstance(sal.get('currency'), dict) else 'USD'} "
                      f"{sal.get('minValue'):,}-{sal.get('maxValue'):,}" if sal.get("minValue") and sal.get("maxValue") else "")
            years = j.get("minYearsExp")
            out.append(Job(source="", title=j.get("title", ""), url=j.get("applyUrl") or j.get("url") or "",
                           company=j.get("companyName", ""), location=location,
                           work_mode="Remote" if remote else ("Hybrid" if j.get("hybrid") in (True, "True") else ""),
                           posted=posted, salary=salary, experience=f"{years}+ yrs" if years not in (None, "", "0", 0) else ""))
        nxt = (data.get("meta") or {}).get("sequence")
        if not jobs or not nxt or len(jobs) < 100:
            break
        meta = {"size": 100, "sequence": nxt}
    return out


def fetch(cfg, profile, log):
    oldest = date.today() - timedelta(days=int(cfg.get("max_age_days") or profile.get("max_age_days", 14)))
    pages = cfg.get("pages", 3)
    jobs, failed, boards = [], 0, 0
    with http_client(log=log) as client:
        for kind, fn in (("getro", _getro), ("consider", _consider)):
            for board, (host, ident) in (cfg.get(kind) or {}).items():
                boards += 1
                try:
                    found = fn(client, board, host, ident, pages, oldest, log)
                except Exception as e:  # one board down must not cost the others
                    failed += 1
                    log(f"WARNING {board} ({kind}) failed: {e!r}"[:200])
                    continue
                for j in found:
                    j.source = f"{cfg['name']}: {board}"
                    j.web3_native = cfg.get("web3_native", False)
                    j.web3_hint = cfg.get("web3_hint", True)
                jobs.extend(found)
                log(f"{board} ({kind}) → {len(found)} recent jobs")
    if boards and failed == boards:
        raise RuntimeError("every VC board failed")
    return jobs
