"""Indian job sites with public search data (added 2026-09-25). Plain HTTP, no login.

  instahyre   /api/v1/job_search?skills=<q>   JSON (title, company, cities; no post date)
  internshala /jobs/keywords-<q>/             server-rendered cards (jobs and paid internships, many WFH)
  cutshort    /jobs/<q>-jobs                  Next.js page data (startups, salary and remote type)
  foundit     /middleware/jobsearch?query=<q> JSON (ex Monster India), needs a Referer header

Their keyword matching is loose, like Naukri's, so scoring does the filtering. Each site runs on
its own: one failing keeps the others.

Config:
  sites    which of the above (default all)
  queries  search words (default blockchain, crypto, web3, cryptocurrency)
  delay_seconds  pause between requests (default 2)
"""
from __future__ import annotations

import json
import re
import time

from bs4 import BeautifulSoup

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, html_to_text, http_client, to_date


def _instahyre(client, q, cfg):
    data = client.get("https://www.instahyre.com/api/v1/job_search", params={"skills": q, "limit": 35}).json()
    for o in data.get("objects") or []:
        locations = o.get("locations") or ""
        yield Job(source="", title=o.get("title") or o.get("candidate_title") or "", url=o.get("public_url", ""),
                  company=(o.get("employer") or {}).get("company_name", ""), location=locations,
                  work_mode=detect_work_mode(locations),
                  description=" ".join(o.get("keywords") or []))


def _internshala(client, q, cfg):
    for path in (f"/jobs/keywords-{q}/", f"/internships/keywords-{q}/"):
        soup = BeautifulSoup(client.get("https://internshala.com" + path).text, "lxml")
        for card in soup.select("div.individual_internship"):
            link = card.get("data-href") or ""
            title = card.select_one(".job-internship-name")
            if not link or not title:
                continue
            company = card.select_one(".company-name")
            loc = card.select_one(".locations")
            about = card.select_one(".about_job .text")
            items = [x.get_text(" ", strip=True) for x in card.select(".row-1-item")]
            salary = next((i for i in items if "₹" in i), "")
            exp = next((i for i in items if "year" in i.lower()), "")
            location = loc.get_text(" ", strip=True) if loc else ""
            yield Job(source="", title=title.get_text(" ", strip=True), url="https://internshala.com" + link,
                      company=company.get_text(" ", strip=True) if company else "", location=location,
                      work_mode=detect_work_mode(location), salary=salary.replace("/year", "").strip(),
                      experience=exp, description=(about.get_text(" ", strip=True) if about else "")[:3000],
                      kind="freelance" if path.startswith("/internships") else "job")


def _cutshort(client, q, cfg):
    html = client.get(f"https://cutshort.io/jobs/{q}-jobs").text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("cutshort page has no data block (layout changed?)")
    data = json.loads(m.group(1))
    page_props = (data.get("props") or {}).get("pageProps") or {}
    queries = (page_props.get("dehydratedState") or {}).get("queries") or []   # null when a search has no jobs
    jobs = []
    for qq in queries:
        inner = (((qq or {}).get("state") or {}).get("data") or {}).get("data")
        if isinstance(inner, dict) and isinstance(inner.get("pageData"), dict):
            jobs = inner["pageData"].get("jobs") or []
            break
    for j in jobs:
        exp = j.get("expRange") or {}
        remote = j.get("remoteType") in ("remote_only", "remote_friendly")
        location = j.get("locationsText") or ", ".join(j.get("locations") or [])
        yield Job(source="", title=j.get("headline", ""), url=j.get("publicUrl", ""),
                  company=(j.get("companyDetails") or {}).get("name", ""),
                  location=location or ("Remote" if remote else ""),
                  work_mode="Remote" if j.get("remoteType") == "remote_only" else detect_work_mode(location),
                  salary=j.get("salaryRangeText") or "",
                  experience=f"{exp.get('min')}-{exp.get('max')} yrs" if exp.get("min") is not None else "",
                  description=html_to_text(j.get("sanitizedComment")) + " " + " ".join(j.get("allSkills") or []))


def _foundit(client, q, cfg):
    resp = client.get("https://www.foundit.in/middleware/jobsearch",
                      params={"sort": 1, "limit": 50, "query": q},
                      headers={"Accept": "application/json, text/plain, */*",
                               "Referer": f"https://www.foundit.in/srp/results?query={q}"})
    for j in (resp.json().get("jobSearchResponse") or {}).get("data") or []:
        if str(j.get("isJobActive", "True")) == "False":
            continue
        lo, hi = (j.get("minimumExperience") or {}).get("years"), (j.get("maximumExperience") or {}).get("years")
        locations = j.get("locations") or ""
        yield Job(source="", title=j.get("title", ""), url="https://www.foundit.in" + (j.get("seoJdUrl") or j.get("jdUrl") or ""),
                  company=j.get("companyName", ""), location=locations, work_mode=detect_work_mode(locations),
                  posted=to_date(j.get("createdAt")), salary="" if j.get("salary") in ("0-0 INR", None) else j.get("salary"),
                  experience=f"{lo}-{hi} yrs" if hi else "", description=str(j.get("skills") or ""))


SITES = {"instahyre": _instahyre, "internshala": _internshala, "cutshort": _cutshort, "foundit": _foundit}


def fetch(cfg, profile, log):
    sites = cfg.get("sites") or list(SITES)
    queries = cfg.get("queries") or ["blockchain", "crypto", "web3", "cryptocurrency"]
    jobs, dead = [], 0
    with http_client(log=log) as client:
        for site in sites:
            found, errors = 0, 0
            for q in queries:
                try:
                    for job in SITES[site](client, q, cfg):
                        job.source = f"{cfg['name']}: {site}"
                        jobs.append(job)
                        found += 1
                except Exception as e:
                    errors += 1
                    log(f"WARNING {site} '{q}' failed: {e!r}"[:180])
                time.sleep(cfg.get("delay_seconds", 2))
            if errors == len(queries):
                dead += 1
            log(f"{site}: {found} jobs")
    if dead == len(sites):
        raise RuntimeError("every Indian job site failed")
    return jobs
