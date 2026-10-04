"""Superteam Earn (superteam.fun/earn) — paid crypto bounties and short projects.

Uses the same public JSON the site loads. Every listing is freelance work with a USD-stable reward
(USDC/USDG) and a deadline. Superteam India is one of its most active chapters.

IMPORTANT: many bounties are open to one country only ("This listing is only open for people in
Nigeria"). The listing *list* endpoint reports region: null for every one of them, so the region is
read from each listing's detail endpoint and anything you can't enter is dropped.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from jobhunter.models import Job
from jobhunter.util import http_client, to_date

API = "https://superteam.fun/api/listings"
DETAIL = "https://superteam.fun/api/listings/details/{}"


def _region(slug):
    """Region comes only from the detail endpoint ("Global", "India", "Nigeria", …)."""
    try:
        with http_client() as client:
            return client.get(DETAIL.format(slug), headers={"Accept": "application/json"}).json().get("region")
    except Exception:
        return None


def fetch(cfg, profile, log):
    jobs, skipped = [], []
    today = date.today()
    eligible = {r.lower() for r in cfg.get("eligible_regions", ["global", "india"])}
    with http_client(log=log) as client:
        listings = client.get(API, params={"take": 100}, headers={"Accept": "application/json"}).json()
        try:
            projects = client.get(API, params={"take": 100, "tab": "projects"}, headers={"Accept": "application/json"}).json()
        except Exception as e:
            log(f"WARNING projects tab failed ({type(e).__name__}), bounties only this time")
            projects = []
        seen, open_listings = set(), []
        for x in listings + projects:
            if x["id"] in seen or x.get("status") != "OPEN" or x.get("agentAccess") == "AGENT_ONLY":
                continue
            seen.add(x["id"])
            deadline = to_date(x.get("deadline"))
            if deadline and deadline < today:
                continue
            if x.get("compensationType") == "range" and x.get("minRewardAsk"):
                reward = f"{x['minRewardAsk']}-{x.get('maxRewardAsk')} {x.get('token', '')}"
            elif x.get("rewardAmount"):
                reward = f"{x['rewardAmount']} {x.get('token', '')}"
            else:
                reward = "variable"
            subs = (x.get("_count") or {}).get("Submission")
            open_listings.append((x, deadline, reward, subs))

        regions = dict(zip([x["slug"] for x, *_ in open_listings],
                           ThreadPoolExecutor(max_workers=8).map(_region, [x["slug"] for x, *_ in open_listings])))
        for x, deadline, reward, subs in open_listings:
            region = regions.get(x["slug"]) or "Global"
            if region.lower() not in eligible:
                skipped.append(f"{region}")
                continue
            jobs.append(Job(
                source=cfg["name"], title=x["title"], url=f"https://superteam.fun/earn/listing/{x['slug']}",
                company=(x.get("sponsor") or {}).get("name", ""), location=region, work_mode="Remote",
                posted=to_date(x.get("publishedAt") or x.get("createdAt")), salary=reward,
                experience=f"{x.get('type', 'bounty')}" + (f" · {subs} submissions" if subs is not None else ""),
                description=f"{x['title']} {x.get('type', '')} solana crypto bounty",
                web3_native=True, kind="freelance", deadline=deadline,
            ))
    if skipped:
        log(f"skipped {len(skipped)} country-locked listings ({', '.join(f'{k}×{v}' for k, v in Counter(skipped).most_common(6))})")
    log(f"{len(jobs)} open bounties/projects you can enter")
    return jobs
