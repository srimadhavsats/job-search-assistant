"""Hacker News "Ask HN: Who is hiring?" (added 2026-09-25), via the public Algolia HN API.

Once a month the whoishiring account opens a thread; each top comment is one company's hiring post
("Company | Role | Location | REMOTE | link"). Only posts that mention crypto words are kept. Many
say REMOTE (worldwide) outright, which suits the remote goal.

Config:
  queries  words to search in the latest thread (default crypto, blockchain, web3, stablecoin, defi)
"""
from __future__ import annotations

import re

from jobhunter.models import Job
from jobhunter.scoring import _hits
from jobhunter.util import detect_work_mode, html_to_text, http_client, to_date

ALGOLIA = "https://hn.algolia.com/api/v1"


def fetch(cfg, profile, log):
    jobs, seen = [], set()
    with http_client(log=log) as client:
        stories = client.get(f"{ALGOLIA}/search_by_date", params={"tags": "story,author_whoishiring", "hitsPerPage": 6}).json()
        thread = next((h for h in stories.get("hits", []) if "who is hiring" in h.get("title", "").lower()), None)
        if not thread:
            raise RuntimeError("no 'Who is hiring' thread found")
        log(f"thread: {thread['title']}")
        for q in cfg.get("queries") or ["crypto", "blockchain", "web3", "stablecoin", "defi", "bitcoin"]:
            data = client.get(f"{ALGOLIA}/search", params={"tags": f"comment,story_{thread['objectID']}",
                                                           "query": q, "hitsPerPage": 100}).json()
            for h in data.get("hits", []):
                if h["objectID"] in seen or h.get("parent_id") != int(thread["objectID"]):
                    continue  # replies to posts are questions, not jobs
                seen.add(h["objectID"])
                text = html_to_text(h.get("comment_text"))
                if len(_hits(text.lower(), profile["scoring"]["web3_terms"])) < 2:
                    continue  # one passing mention is not a crypto company
                head = text.split(". ")[0][:220]
                parts = [p.strip() for p in re.split(r"\s\|\s", head)]
                company = parts[0][:60] if parts else ""
                role = next((p for p in parts[1:] if re.search(r"engineer|analyst|support|operations|developer|"
                                                               r"manager|designer|research|community|lead|scientist", p, re.I)), "")
                location = " / ".join(p for p in parts[1:] if re.search(r"remote|onsite|on-site|hybrid|[A-Z][a-z]+,", p, re.I))[:80]
                links = re.findall(r"https?://[^\s<>\"')]+", h.get("comment_text") or "")
                jobs.append(Job(source=cfg["name"], title=(role or "Several roles (see post)")[:120],
                                url=f"https://news.ycombinator.com/item?id={h['objectID']}",
                                company=company, location=location, work_mode=detect_work_mode(location, head),
                                posted=to_date(h.get("created_at")), description=text[:6000] + " " + " ".join(links[:3])))
        log(f"{len(jobs)} crypto hiring posts")
    return jobs
