"""apna.co (India's mass job app, added 2026-09-24 at the owner's request).

The public search page (`/jobs?search=true&text=<q>&page=<n>`, 25 jobs a page) is server-rendered
and embeds each card as JSON (`"data":{"jobID":…,"jobTitle":…}`) in the Next.js payload, so plain
HTTP works; no login, no browser. Cards carry title, company, city, salary and tags (work mode,
experience) but no date or description, so each job's own page is fetched for its schema.org
`JobPosting` block (`<script id="jdp-job-schema">`: description, datePosted).

Apna's keyword matching is loose ("crypto exchange" returns London Stock Exchange jobs), so
scoring does the filtering, as with Naukri.

Blocking: the site sits behind Link11. The first test run (10 searches + ~150 job pages, 6 in
parallel, in 36 s) got the IP an HTTP 481 "Link11 access denied" on apna.co within a minute
(the app's API host production.apna.co stayed reachable). So: one request at a time, random
3-6 s pauses, job pages only for cards whose title/company look relevant (`detail_words`),
capped by `max_details`, and any 403/429/481 stops the source and keeps what it has.

Config keys:
  searches      list of "query" or {q, pages}   (default pages: 1)
  max_details   job pages to fetch per run (default 30)
  detail_words  a card needs one of these in title/company to get its page fetched
  delay_seconds base pause between requests (default 3, randomised up to 2x)
"""
from __future__ import annotations

import json
import random
import re
import time
from urllib.parse import quote

from jobhunter.models import Job
from jobhunter.util import html_to_text, http_client, to_date

BASE = "https://apna.co"
_CARD = re.compile(r'"data":\{"jobID":')
_SCHEMA = re.compile(r'<script id="jdp-job-schema" type="application/ld\+json">(.*?)</script>', re.S)


def _cards(html: str) -> list[dict]:
    text = html.replace('\\"', '"')
    dec, out = json.JSONDecoder(), {}
    for m in _CARD.finditer(text):
        try:
            card, _ = dec.raw_decode(text, m.start() + len('"data":'))
        except ValueError:
            continue
        if card.get("jobID") and card.get("jobPublicURL"):
            out[card["jobID"]] = card
    return list(out.values())


BLOCKED = {403, 429, 481}


class Blocked(Exception):
    pass


def _get(client, url: str, cfg: dict) -> str:
    time.sleep(random.uniform(1, 2) * float(cfg.get("delay_seconds", 3)))
    r = client.get(url)
    if r.status_code in BLOCKED:
        raise Blocked(f"HTTP {r.status_code}")
    return r.text if r.status_code == 200 else ""


def _details(html: str) -> dict:
    try:
        m = _SCHEMA.search(html)
        return json.loads(m.group(1)) if m else {}
    except ValueError:  # one broken page must not sink the source
        return {}


def _salary(card: dict) -> str:
    s = card.get("jobSalaryRangeDetails") or {}
    lo, hi = s.get("salaryMin") or 0, s.get("salaryMax") or 0
    return f"₹{lo:,} - ₹{hi:,} per month" if hi else ""


def fetch(cfg, profile, log):
    searches = [s if isinstance(s, dict) else {"q": s} for s in cfg.get("searches", [])]
    words = [w.lower() for w in cfg.get("detail_words", [])]
    cards: dict[int, dict] = {}
    details: dict[int, dict] = {}
    with http_client(tries=2, retry_429=False) as client:  # Link11 punishes retries
        try:
            for s in searches:
                for page in range(1, int(s.get("pages", 1)) + 1):
                    url = f"{BASE}/jobs?search=true&text={quote(s['q'])}" + (f"&page={page}" if page > 1 else "")
                    found = _cards(_get(client, url, cfg))
                    new = [c for c in found if c["jobID"] not in cards]
                    cards.update({c["jobID"]: c for c in found})
                    log(f"'{s['q']}' p{page} → {len(found)} ({len(new)} new)")
                    if len(found) < 20:
                        break
            wanted = [c for c in cards.values() if not words or any(
                w in f"{c['jobTitle']} {(c.get('jobOrganisationDetails') or {}).get('organisationName', '')}".lower()
                for w in words)][: int(cfg.get("max_details", 30))]
            for c in wanted:
                details[c["jobID"]] = _details(_get(client, BASE + c["jobPublicURL"], cfg))
        except Blocked as e:
            log(f"WARNING: blocked by apna.co ({e}), keeping {len(cards)} jobs found so far")
    log(f"{len(cards)} jobs, read {sum(1 for d in details.values() if d)} job pages")
    todo = [(c, details.get(c["jobID"], {})) for c in cards.values()]

    jobs = []
    for card, d in todo:
        tags = [t.get("tagLabel", "") for t in card.get("jobUITags") or []]
        exp = next((t for t in tags if "year" in t.lower() or "experience" in t.lower()), "")
        location = card.get("jobCardAddress") or ""
        remote = "Work from Home" in (location, *tags)
        jobs.append(Job(
            source=cfg["name"], title=card["jobTitle"].strip(), url=BASE + card["jobPublicURL"],
            company=(card.get("jobOrganisationDetails") or {}).get("organisationName", "").strip(),
            location="Remote, India" if remote else f"{location}, India",
            work_mode="Remote" if remote else ("Onsite" if "Work from Office" in tags else ""),
            posted=to_date(d.get("datePosted")), salary=_salary(card),
            experience="" if exp == "Any experience" else exp,
            description=html_to_text(d.get("description")),
            kind="freelance" if "Part Time" in tags else "job",
        ))
    return jobs
