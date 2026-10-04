"""Generic RSS/Atom job feed.

Config keys:
  url            feed URL (or `urls: [...]`)
  company_from   author | title_at | <entry field name>     (optional)
  location_from  <entry field name, e.g. media_location>     (optional)
"""
import html

import feedparser

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, html_to_text, http_client, to_date


def fetch(cfg, profile, log):
    jobs = []
    urls = cfg.get("urls") or [cfg["url"]]
    failed = 0
    with http_client(log=log) as client:
        for url in urls:
            try:
                feed = feedparser.parse(client.get(url).text)
            except Exception as e:  # already retried; one dead feed must not cost the others
                failed += 1
                log(f"WARNING {url} failed after retries ({type(e).__name__}), skipped")
                continue
            log(f"{url} → {len(feed.entries)} entries")
            for e in feed.entries:
                title = html.unescape(e.get("title", "")).strip()  # some feeds double-escape "&" as "&amp;"
                company = ""
                how = cfg.get("company_from")
                if how == "title_at" and " at " in title:
                    title, company = title.rsplit(" at ", 1)
                elif how:
                    company = e.get(how, "")
                location = e.get(cfg["location_from"], "") if cfg.get("location_from") else ""
                description = html_to_text(e.get("summary") or e.get("description"))
                jobs.append(Job(
                    source=cfg["name"], title=title.strip(), url=e.get("link", ""),
                    company=company.strip(), location=location,
                    work_mode=detect_work_mode(title, location, description[:600]),
                    posted=to_date(e.get("published_parsed") or e.get("updated_parsed")),
                    description=description, web3_native=cfg.get("web3_native", False),
                ))
    if failed == len(urls):
        raise RuntimeError("every feed failed")
    return jobs
