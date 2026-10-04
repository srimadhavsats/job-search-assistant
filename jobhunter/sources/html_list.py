"""Generic job-list page scraped with CSS selectors.

Config keys:
  urls          list of listing pages
  base_url      prefix for relative links
  pages         how many pages per url (default 1)
  page_param    query parameter for page number (default "page")
  item          CSS selector for one job card
  fields        {title, company, location, posted, salary, link, description}: "css selector" or "css selector@attribute"
  delay_seconds pause between requests (default 1.5)
  browser_fallback  true = if a page is refused by a bot check, open it in headless Chrome instead

A page that times out or errors is retried (util.http_client), then skipped with a warning; the other
pages still count. On 2026-09-25 one web3.career timeout threw away all ~390 jobs of that run.
"""
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from jobhunter.models import Job
from jobhunter.net import browser_get, looks_blocked
from jobhunter.util import detect_work_mode, http_client, to_date


def _get(card, spec):
    if not spec:
        return ""
    selector, _, attr = spec.partition("@")
    node = card.select_one(selector) if selector else card
    if node is None:
        return ""
    return (node.get(attr) or "") if attr else node.get_text(" ", strip=True)


def fetch(cfg, profile, log):
    jobs, fields = [], cfg["fields"]
    delay = cfg.get("delay_seconds", 1.5)
    failed = 0
    with http_client(log=log) as client:
        for url in cfg["urls"]:
            for page in range(1, cfg.get("pages", 1) + 1):
                page_url = url if page == 1 else f"{url}{'&' if '?' in url else '?'}{cfg.get('page_param', 'page')}={page}"
                try:
                    resp = client.get(page_url)
                except Exception as e:  # already retried; skip this listing page, keep the rest
                    failed += 1
                    log(f"WARNING {page_url} failed after retries ({type(e).__name__}), skipped")
                    break
                text = resp.text
                if resp.status_code != 200 and cfg.get("browser_fallback") and looks_blocked(resp):
                    text = browser_get(page_url) or ""
                    log(f"{page_url} refused plain HTTP ({resp.status_code}), browser fallback "
                        + ("worked" if text else "failed"))
                elif resp.status_code != 200:
                    log(f"{page_url} → HTTP {resp.status_code}")
                    break
                cards = BeautifulSoup(text, "lxml").select(cfg["item"])
                log(f"{page_url} → {len(cards)} jobs")
                for card in cards:
                    title = _get(card, fields.get("title"))
                    link = _get(card, fields.get("link"))
                    if not title or not link:
                        continue
                    location = _get(card, fields.get("location")).replace("📍", "").strip()
                    jobs.append(Job(
                        source=cfg["name"], title=title,
                        url=urljoin(cfg.get("base_url", url), link),
                        company=_get(card, fields.get("company")), location=location,
                        work_mode=detect_work_mode(title, location),
                        posted=to_date(_get(card, fields.get("posted"))),
                        salary=_get(card, fields.get("salary")),
                        description=_get(card, fields.get("description"))[:6000],
                        web3_native=cfg.get("web3_native", False),
                    ))
                if not cards:
                    break
                time.sleep(delay)
    if failed and not jobs:
        raise RuntimeError(f"all {failed} listing pages failed")
    return jobs
