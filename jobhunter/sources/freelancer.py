"""Freelancer.com crypto projects (added 2026-09-25), via its public project search API (no login).

Everything here is freelance work, so it goes to the Freelance tab with its own scoring. Freelancer
has many low-budget and copycat crypto dev gigs; scoring and the scam and identity-rental filters
decide what is worth a look.

Config:
  queries   search words (default blockchain, crypto, web3, smart contract, defi, crypto research)
"""
from __future__ import annotations

from jobhunter.models import Job
from jobhunter.util import http_client, to_date

API = "https://www.freelancer.com/api/projects/0.1/projects/active/"


def fetch(cfg, profile, log):
    jobs, seen = [], set()
    with http_client(log=log) as client:
        for q in cfg.get("queries") or ["blockchain", "crypto", "web3", "smart contract", "defi", "crypto research", "telegram moderator"]:
            data = client.get(API, params={"query": q, "limit": 50, "full_description": "true",
                                           "job_details": "true", "sort_field": "time_updated"}).json()
            projects = (data.get("result") or {}).get("projects") or []
            for p in projects:
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                budget = p.get("budget") or {}
                cur = (p.get("currency") or {}).get("code", "USD")
                lo, hi = budget.get("minimum"), budget.get("maximum")
                salary = f"{lo:,.0f}-{hi:,.0f} {cur}" if lo and hi else (f"{lo:,.0f} {cur}" if lo else "")
                if p.get("type") == "hourly":
                    salary += " per hour"
                skills = " ".join(j.get("name", "") for j in p.get("jobs") or [])
                jobs.append(Job(source=cfg["name"], title=p.get("title", ""),
                                url=f"https://www.freelancer.com/projects/{p.get('seo_url') or p['id']}",
                                company="Freelancer client", location="Remote", work_mode="Remote",
                                posted=to_date(p.get("time_submitted")), salary=salary,
                                experience=f"{(p.get('bid_stats') or {}).get('bid_count', 0)} submissions",
                                description=f"{p.get('description') or p.get('preview_description') or ''} {skills}"[:6000],
                                kind="freelance"))
            log(f"'{q}' → {len(projects)} projects")
    return jobs
