"""NaukriGulf.com — jobs in the UAE, Saudi Arabia, Qatar, Bahrain, Oman and Kuwait.

Same protection and same approach as Naukri (see naukri.py): plain requests time out, so the normal
search page is opened in your installed Chrome (headless, own persistent profile) and the JSON the
page loads (spapi/jobapi/search) is read. Page 2 of a search is "<slug>-jobs-2" (offset 30).

Gulf employers sponsor the work visa for every foreign hire, so scoring treats these locations as
visa-sponsored (profile.yaml → scoring → visa_typical_locations).
"""
import random
import re
import time
from pathlib import Path

from jobhunter.models import Job
from jobhunter.sources import naukri
from jobhunter.util import detect_work_mode, html_to_text, to_date

PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "browser_profiles" / "naukrigulf"
BASE = "https://www.naukrigulf.com"


def _url(query, page):
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return f"{BASE}/{slug}-jobs{'' if page == 1 else f'-{page}'}"


def _to_job(j, source):
    exp = j.get("experience") or {}
    location = j.get("location") or ""
    return Job(
        source=source, title=j.get("designation", ""), url=f"{BASE}/{j.get('jdURL', '')}",
        company=(j.get("company") or {}).get("name", "").strip(), location=location,
        work_mode=detect_work_mode(location, j.get("designation", "")),
        posted=to_date(j.get("latestPostedDate")),
        experience=f"{exp.get('min')}-{exp.get('max')} Yrs" if exp.get("min") else "",
        description=html_to_text(j.get("description") or j.get("jobInfo")),
    )


def fetch(cfg, profile, log):
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    jobs, blocks = [], 0
    with sync_playwright() as p:
        ctx, page = naukri._launch(p, cfg, PROFILE_DIR)  # own profile: runs in parallel with Naukri
        try:
            page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            naukri._human_pause(cfg)
            for query in profile.get("naukrigulf_searches", ["blockchain", "crypto", "web3"]):
                for n in range(1, cfg.get("pages_per_search", 2) + 1):
                    try:
                        with page.expect_response(lambda r: "spapi/jobapi/search" in r.url, timeout=40000) as info:
                            page.goto(_url(query, n), wait_until="domcontentloaded", timeout=60000)
                        resp = info.value
                        if resp.status in (403, 406, 429):
                            raise PWTimeout(f"HTTP {resp.status}")
                        data = resp.json()
                    except PWTimeout as e:
                        blocks += 1
                        log(f"'{query}' p{n} → blocked or no response ({str(e)[:50]})")
                        if blocks >= 3:
                            log("WARNING: Naukri Gulf blocked 3 times — stopped early; results so far are kept")
                            return jobs
                        time.sleep(60 * blocks)
                        break
                    except Exception as e:
                        log(f"WARNING: '{query}' p{n} FAILED: {e!r}"[:200])
                        break

                    found = data.get("jobs") or []
                    log(f"'{query}' p{n} → {len(found)} (of {data.get('totalJobsCount', '?')})")
                    jobs.extend(_to_job(j, cfg["name"]) for j in found)
                    page.mouse.wheel(0, random.randint(400, 1400))
                    naukri._human_pause(cfg)
                    if len(found) < 30 or n * 30 >= int(data.get("totalJobsCount") or 0):
                        break
        finally:
            ctx.close()
    return jobs
