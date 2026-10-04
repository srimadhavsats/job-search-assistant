"""Naukri.com.

How Naukri protects itself (checked 2026-09-17):
  - Akamai Bot Manager (ak_bmsc / bm_sv cookies) scores every visitor on behaviour and reputation.
  - Each search API call carries an `nkparam` token signed by Naukri's own page JavaScript, so
    calling the JSON API directly gets "406 recaptcha required".

So this opens the normal search page in your installed Google Chrome (headless) and reads the JSON
the page itself loads. To avoid being blocked it behaves like a returning visitor instead of a fresh
bot on every run:
  - a persistent browser profile (data/browser_profiles/naukri), so cookies survive between runs
  - a warm-up visit to the home page, random human-like pauses and a little scrolling
  - on a block: back off (60 s, then 120 s), clear cookies, warm up again; give up after 3 blocks
It never solves CAPTCHAs or forges Naukri's signed tokens.
"""
import random
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from jobhunter.models import Job
from jobhunter.util import UA, detect_work_mode, html_to_text, to_date

PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "browser_profiles" / "naukri"


def _placeholder(job, kind):
    return next((p.get("label", "") for p in job.get("placeholders") or [] if p.get("type") == kind), "")


def _search_url(query, page, days):
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return f"https://www.naukri.com/{slug}-jobs{'' if page == 1 else f'-{page}'}?k={quote(query)}&jobAge={days}"


def _human_pause(cfg, scale=1.0):
    base = cfg.get("delay_seconds", 4)
    time.sleep(random.uniform(base * 0.75, base * 1.6) * scale)


def _launch(p, cfg, profile_dir=PROFILE_DIR):
    def launch():
        return p.chromium.launch_persistent_context(
            str(profile_dir), channel="chrome", headless=cfg.get("headless", True),
            # headless Chrome says "HeadlessChrome" in its user agent, which Akamai blocks outright
            user_agent=UA, locale="en-IN", timezone_id="Asia/Kolkata", viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])

    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        ctx = launch()
    except Exception:  # profile left locked/corrupted by a crashed run: start a fresh one
        shutil.rmtree(profile_dir, ignore_errors=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        ctx = launch()
    return ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())


def _warm_up(page, cfg):
    page.goto("https://www.naukri.com/", wait_until="domcontentloaded", timeout=45000)
    _human_pause(cfg)
    page.mouse.wheel(0, random.randint(300, 900))
    _human_pause(cfg, 0.5)


def fetch(cfg, profile, log):
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    days = min(int(profile.get("max_age_days", 14)), 30)
    jobs = []
    with sync_playwright() as p:
        ctx, page = _launch(p, cfg)
        try:
            _warm_up(page, cfg)
            if "access denied" in page.title().lower():
                log("WARNING: Naukri blocked even the home page — this network is temporarily blocked. "
                    "Skipping Naukri this run; it usually clears within a few hours.")
                return jobs
            blocks = 0
            for search in profile["naukri_searches"]:
                query, pages = ((search, cfg.get("pages_per_search", 1)) if isinstance(search, str)
                                else (search["q"], search.get("pages", 1)))
                for n in range(1, pages + 1):
                    try:
                        with page.expect_response(lambda r: "jobapi/v3/search" in r.url, timeout=30000) as info:
                            page.goto(_search_url(query, n, days), wait_until="domcontentloaded", timeout=45000)
                        resp = info.value
                        if resp.status in (403, 406, 429) or "access denied" in page.title().lower():
                            raise PWTimeout(f"search API answered HTTP {resp.status}")
                        if resp.status != 200:  # e.g. 400 for a page past the last result: not a block
                            log(f"'{query}' p{n} → HTTP {resp.status}, skipping this search")
                            break
                        data = resp.json()
                    except PWTimeout as e:
                        blocks += 1
                        log(f"'{query}' p{n} → blocked ({page.title()!r}; {str(e)[:60]})")
                        if blocks >= 3:
                            log("WARNING: Naukri blocked 3 times — stopped early; results so far are kept")
                            return jobs
                        wait = 60 * blocks
                        log(f"backing off {wait}s, clearing cookies and warming up again")
                        time.sleep(wait)
                        ctx.clear_cookies()
                        _warm_up(page, cfg)
                        break
                    except Exception as e:
                        log(f"WARNING: '{query}' p{n} FAILED: {e!r}"[:200])
                        break

                    found = data.get("jobDetails") or []
                    log(f"'{query}' p{n} → {len(found)} (of {data.get('noOfJobs', '?')})")
                    for j in found:
                        location = _placeholder(j, "location")
                        jd = j.get("jdURL", "")
                        salary = _placeholder(j, "salary")
                        jobs.append(Job(
                            source=cfg["name"], title=j.get("title", ""),
                            url=jd if jd.startswith("http") else "https://www.naukri.com" + jd,
                            company=j.get("companyName", ""), location=location,
                            work_mode=detect_work_mode(location, j.get("title", "")),
                            posted=to_date(j.get("createdDate")),
                            salary="" if salary == "Not disclosed" else salary,
                            experience=_placeholder(j, "experience"),
                            description=" ".join([html_to_text(j.get("jobDescription")), j.get("tagsAndSkills", "")]),
                        ))
                    page.mouse.wheel(0, random.randint(400, 1600))  # scroll the results like a person would
                    _human_pause(cfg)
                    if len(found) < 20 or n * 20 >= int(data.get("noOfJobs") or 0):
                        break
        finally:
            ctx.close()
    return jobs
