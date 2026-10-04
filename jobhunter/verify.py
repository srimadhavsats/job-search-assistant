"""Open each good job's apply page and answer two questions (added 2026-09-25):

  1. Is it still open?  404/410, "no longer accepting applications", "this job has expired"…
  2. Can someone in India apply?  The full page text is checked with the same rules as scoring
     (required language, "based in the US", students only) plus work-permit wording ("must be
     authorized to work in the United States"). Listings from boards without descriptions
     (VC boards, web3.career cards, Telegram digests) are only judged properly this way.

Results go to the "Link check" column and are cached in seen_jobs.sqlite (link_checks), so a job is
opened at most once a day. A lock found on the page caps the score like any region lock.
Company career APIs re-list every open job each check, so those rows need no page visit.

VC portfolio board rows (`hint_sources`) have no description, so their page text is saved to job_text.
When it has no web3 word the row is flagged and capped like a weak web3 match, and scoring does the same
on the next fetch (Veem, a payments company on Pantera's board, was #4 in the queue on 2026-09-26).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from jobhunter.scoring import PORTFOLIO_NOT_CRYPTO, WORK_AUTH, _hits, out_of_reach
from jobhunter.util import http_client

CLOSED_PHRASES = ("no longer accepting applications", "this job is no longer available", "job is no longer available",
                  "this job has expired", "job has expired", "this position has been filled", "position has been filled",
                  "this position is closed", "this job is closed", "job posting is no longer", "posting has been removed",
                  "the job you are looking for is no longer", "this job has been closed", "no longer open",
                  "this listing has expired", "applications are closed", "this role has been filled",
                  "job not found", "the page you were looking for doesn't exist", "position is no longer available",
                  "this job posting has expired", "sorry, this job has expired", "job is closed")
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "recruitee.com")
SKIP_HOSTS = ("t.me", "naukri.com", "naukrigulf.com", "apna.co", "news.ycombinator.com")
RECHECK = {"open": timedelta(hours=24), "closed": timedelta(days=30), "other": timedelta(hours=8)}


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).lower()


def page_verdict(text: str, title: str, sc: dict) -> tuple[str, str]:
    """(result, flag) for a job page's visible text. result: open | closed. flag: why India can't apply, or ""."""
    head = text[:4000]
    if any(p in head for p in CLOSED_PHRASES) or any(p in text for p in CLOSED_PHRASES[:3]):
        return "closed", ""
    flag = out_of_reach(title.lower(), text[:20000], sc) or ""
    if flag.startswith("Text requires"):
        flag = "Apply page requires" + flag[len("Text requires"):]
    elif flag:
        flag = f"Apply page, {flag[0].lower()}{flag[1:]}"
    return "open", flag


def _ats_text(client, url: str, cache: dict) -> tuple[str, str] | None:
    """Job text straight from the careers API behind an Ashby, Lever or Greenhouse link.

    VC portfolio boards and aggregators link to these pages without a description, and Ashby pages
    are drawn by JavaScript, so the public APIs are read instead. Returns ("closed", "") when the job is
    gone, ("open", text) when it is listed, None when the link is not one of these."""
    from jobhunter.util import html_to_text
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        slug, jid = m.group(1), m.group(2)
        if slug not in cache:
            resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            cache[slug] = {j.get("id"): j for j in (resp.json().get("jobs") or [])} if resp.status_code == 200 else None
        if cache[slug] is None:
            return None
        j = cache[slug].get(jid)
        if not j:
            return "closed", ""
        locs = " ".join([j.get("location") or ""] + [l.get("location", "") for l in j.get("secondaryLocations") or []])
        return "open", f"location {locs}. {j.get('descriptionPlain') or ''}".lower()
    m = re.search(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        resp = client.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", params={"mode": "json"})
        if resp.status_code in (404, 410):
            return "closed", ""
        if resp.status_code != 200:
            return None
        j = resp.json()
        lists = " ".join(html_to_text(l.get("content", "")) for l in j.get("lists") or [])
        loc = (j.get("categories") or {}).get("location", "")
        return "open", f"location {loc}. {j.get('descriptionPlain') or ''} {lists} {j.get('additionalPlain') or ''}".lower()
    m = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
    if m:
        resp = client.get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}")
        if resp.status_code in (404, 410):
            return "closed", ""
        if resp.status_code != 200:
            return None
        j = resp.json()
        return "open", f"location {(j.get('location') or {}).get('name', '')}. {html_to_text(j.get('content'), 20000)}".lower()
    return None


def check_url(client, url: str, title: str, sc: dict, cache: dict | None = None) -> tuple[str, str]:
    return check_page(client, url, title, sc, cache)[:2]


def check_page(client, url: str, title: str, sc: dict, cache: dict | None = None) -> tuple[str, str, str]:
    """(result, flag, page text). The text is "" when the job is closed or the page could not be read."""
    ats = _ats_text(client, url, {} if cache is None else cache)
    if ats is not None:
        result, text = ats
        if result == "closed":
            return "closed", "", ""
        result, flag = page_verdict(text, title, sc)
        loc = re.match(r"location (.*?)\. ", text)
        loc = loc.group(1).strip() if loc else ""
        # the careers site's own location field ("Remote - US", "New York") when the board showed "Remote"
        if not flag and loc and not _hits(loc, sc["india_or_global_locations"]) and not _hits(
                loc, sc.get("visa_typical_locations", [])) and (
                _hits(loc, sc["region_locked_terms"]) or _hits(loc, sc.get("title_region_words", []))):
            flag = f"Apply page lists the location as {loc[:40].title()}"
        return result, flag, text
    m = re.search(r"linkedin\.com/jobs/view/(\d+)", url)
    if m:
        resp = client.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}")
        if resp.status_code in (404, 410):
            return "closed", "", ""
        if resp.status_code != 200:
            return f"could not check (HTTP {resp.status_code})", "", ""
        text = _visible_text(resp.text)
        if "no longer accepting applications" in text:
            return "closed", "", ""
        return (*page_verdict(text, title, sc), text)
    resp = client.get(url)
    if resp.status_code in (404, 410):
        return "closed", "", ""
    if resp.status_code in (401, 403, 429) or resp.status_code >= 500:
        return f"could not check (HTTP {resp.status_code})", "", ""
    final = str(resp.url)
    # redirected from a job page to a generic listing or home page: the job was taken down
    if urlparse(final).path.rstrip("/") in ("", "/jobs", "/careers", "/job-search") and urlparse(url).path.rstrip("/") not in ("", "/jobs"):
        return "closed", "", ""
    text = _visible_text(resp.text)
    return (*page_verdict(text, title, sc), text)


def _due(row: dict, prev: dict | None, now: datetime) -> bool:
    if not prev:
        return True
    if prev.get("url") != row.get("Apply link"):
        return True
    try:
        at = datetime.fromisoformat(prev["checked_at"])
    except (TypeError, ValueError):
        return True
    kind = "open" if prev["result"] == "open" else "closed" if prev["result"] == "closed" else "other"
    return now - at >= RECHECK[kind]


def _portfolio_crypto(row: dict, text: str, sc: dict) -> bool:
    """False only when the saved page text exists and no web3 word is in it, the title or the company."""
    if not text:
        return True
    return bool(_hits(f"{row.get('Title') or ''} {row.get('Company') or ''} {text}".lower(), sc["web3_terms"]))


def _label(result: str, checked_at: str) -> str:
    day = checked_at[5:10] if checked_at else ""
    try:
        day = datetime.fromisoformat(checked_at).strftime("%d %b")
    except (TypeError, ValueError):
        pass
    return {"open": f"Open ({day})", "closed": f"Closed ({day})"}.get(result, f"Could not open ({day})")


def _is_hint(row: dict, hint_sources) -> bool:
    return any(str(row.get("Source") or "").startswith(s) for s in hint_sources)


def apply(rows: list[dict], store, sc: dict, bands: list, log=print, budget: int = 40, min_score: int = 55,
          delay: float = 1.5, cap: int | None = None, hint_sources: tuple = ()) -> dict:
    """Check up to `budget` due rows, then write every row's Link check column and apply page flags."""
    now = datetime.now()
    checks = store.link_checks()
    cap = cap or sc.get("region_locked_max_score", 45)
    todo = []
    for row in rows:
        url = str(row.get("Apply link") or "")
        host = urlparse(url).netloc.lower()
        if (not url.startswith("http") or (row.get("Score") or 0) < min_score
                or str(row.get("Status") or "New") != "New" or any(h in host for h in SKIP_HOSTS)
                or str(row.get("Source") or "").startswith("Company careers")):  # those carry the full text already
            continue
        if _due(row, checks.get(row.get("Key")), now):
            todo.append(row)
    todo.sort(key=lambda r: -(r.get("Score") or 0))
    stats = {"checked": 0, "closed": 0, "locked": 0, "pending": max(0, len(todo) - budget)}
    if todo[:budget]:
        last_host: dict[str, float] = {}
        ats_cache: dict = {}
        with http_client(tries=2, backoff=(5,), retry_429=False) as client:
            for row in todo[:budget]:
                url = str(row["Apply link"])
                host = urlparse(url).netloc
                wait = delay * (2 if "linkedin" in host else 1) - (time.time() - last_host.get(host, 0))
                if wait > 0:
                    time.sleep(wait)
                try:
                    result, flag, text = check_page(client, url, str(row.get("Title") or ""), sc, ats_cache)
                except Exception as e:
                    result, flag, text = f"could not check ({type(e).__name__})", "", ""
                last_host[host] = time.time()
                store.save_link_check(row["Key"], url, result, flag)
                if result == "open" and len(text) > 150 and _is_hint(row, hint_sources):
                    store.save_texts([(row["Key"], text)])
                stats["checked"] += 1
                stats["closed"] += result == "closed"
                stats["locked"] += bool(flag)
        log(f"link check: opened {stats['checked']} apply pages, {stats['closed']} closed, "
            f"{stats['locked']} not open to India" + (f", {stats['pending']} left for later" if stats["pending"] else ""))
        checks = store.link_checks()

    for row in rows:
        c = checks.get(row.get("Key"))
        if not c or c.get("url") != row.get("Apply link"):
            continue
        row["Link check"] = _label(c["result"], c["checked_at"])
        flags = str(row.get("Flags") or "")
        extra = "Closed (apply page says so)" if c["result"] == "closed" else (c.get("flag") or "")
        if not extra and _is_hint(row, hint_sources) and not _portfolio_crypto(row, store.text(row["Key"]), sc):
            extra = PORTFOLIO_NOT_CRYPTO
            row["Score"] = min(row.get("Score") or 0, sc.get("weak_web3_max_score", 100))
            row["Priority"] = next((b["label"] for b in bands or [] if row["Score"] >= b["min"]), row.get("Priority"))
        if extra and extra not in flags:
            row["Flags"] = "; ".join(filter(None, [extra, flags]))
        if extra and extra != PORTFOLIO_NOT_CRYPTO and (row.get("Score") or 0) > cap:
            row["Score"] = cap if c["result"] != "closed" else min(cap, 30)
            row["Priority"] = next((b["label"] for b in bands or [] if row["Score"] >= b["min"]), row.get("Priority"))
    return stats
