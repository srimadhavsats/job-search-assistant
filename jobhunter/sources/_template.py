"""TEMPLATE for a site that the generic rss/html/ats types can't handle.

1. Copy this file to jobhunter/sources/mysite.py
2. Fill in fetch()
3. Add to config/sources.yaml:
     - name: MySite
       type: custom
       module: mysite
       enabled: true
       queries: [blockchain analyst, web3 support]   # any extra keys you add here arrive in `cfg`
4. Test only your source:   run_jobs.bat --only mysite
"""
import time

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, html_to_text, http_client, to_date


def fetch(cfg, profile, log):
    jobs = []
    with http_client() as client:
        for query in cfg.get("queries", ["blockchain"]):  # or ignore queries if the site is web3-only
            resp = client.get("https://example.com/api/jobs", params={"q": query})
            data = resp.json()
            log(f"'{query}' → {len(data)} jobs")
            for item in data:
                jobs.append(Job(
                    source=cfg["name"],
                    title=item["title"],
                    url=item["url"],
                    company=item.get("company", ""),
                    location=item.get("location", ""),
                    work_mode=detect_work_mode(item.get("location", "")),
                    posted=to_date(item.get("date")),
                    description=html_to_text(item.get("description")),
                    web3_native=cfg.get("web3_native", False),
                ))
            time.sleep(cfg.get("delay_seconds", 2))
    return jobs
