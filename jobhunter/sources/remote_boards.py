"""General remote-job boards with public feeds. They list every industry, so only posts mentioning
crypto/web3/blockchain are kept (scoring still does the fine filtering).

Config:
  boards: [remotive, remoteok, weworkremotely, workingnomads]
"""
import feedparser

from jobhunter.models import Job
from jobhunter.scoring import _hits
from jobhunter.util import html_to_text, http_client, to_date

CONTRACT_WORDS = ("contract", "freelance", "part_time", "part-time", "part time")


def _remotive(client):
    seen = {}
    for q in ("crypto", "blockchain", "web3"):
        for j in client.get("https://remotive.com/api/remote-jobs", params={"search": q}).json().get("jobs", []):
            seen[j["id"]] = j
    for j in seen.values():
        yield dict(title=j["title"], company=j["company_name"], url=j["url"],
                   location=j.get("candidate_required_location", ""), salary=j.get("salary", ""),
                   posted=j.get("publication_date"), description=html_to_text(j.get("description")),
                   contract=j.get("job_type", ""))


def _remoteok(client):
    seen = {}
    for tag in ("crypto", "web3", "blockchain"):
        for j in client.get("https://remoteok.com/api", params={"tags": tag}).json()[1:]:  # [0] is the legal notice
            seen[j["id"]] = j
    for j in seen.values():
        lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
        yield dict(title=j.get("position", ""), company=j.get("company", ""), url=j.get("url", ""),
                   location=j.get("location") or "Remote", salary=f"${lo:,}-${hi:,}" if hi else "",
                   posted=j.get("date"), description=html_to_text(j.get("description")) + " " + " ".join(j.get("tags") or []),
                   contract=" ".join(j.get("tags") or []))


def _weworkremotely(client):
    feed = feedparser.parse(client.get("https://weworkremotely.com/remote-jobs.rss").text)
    for e in feed.entries:
        company, _, title = e.get("title", "").partition(": ")
        yield dict(title=title or company, company=company if title else "", url=e.get("link", ""),
                   location=e.get("region", "Remote"), salary="", posted=e.get("published_parsed"),
                   description=html_to_text(e.get("summary")), contract=e.get("type", ""))


def _workingnomads(client):
    for j in client.get("https://www.workingnomads.com/api/exposed_jobs/").json():
        yield dict(title=j.get("title", ""), company=j.get("company_name", ""), url=j.get("url", ""),
                   location=j.get("location") or "Remote", salary="", posted=j.get("pub_date"),
                   description=html_to_text(j.get("description")) + " " + (j.get("tags") or ""), contract="")


BOARDS = {"remotive": _remotive, "remoteok": _remoteok, "weworkremotely": _weworkremotely,
          "workingnomads": _workingnomads}


def fetch(cfg, profile, log):
    web3_terms = profile["scoring"]["web3_terms"]
    jobs = []
    for board in cfg.get("boards", BOARDS):
        items = None
        for attempt in (1, 2):  # these boards occasionally time out; one retry clears most of those
            try:
                with http_client() as client:
                    items = list(BOARDS[board](client))
                break
            except Exception as e:
                if attempt == 2:
                    log(f"WARNING: {board} FAILED: {e!r}"[:200])
        if items is None:
            continue
        kept = 0
        for it in items:
            if not _hits(f"{it['title']} {it['company']} {it['description']}".lower(), web3_terms):
                continue
            kept += 1
            contract = any(w in str(it["contract"]).lower() for w in CONTRACT_WORDS)
            jobs.append(Job(
                source=f"{cfg['name']}: {board}", title=it["title"], url=it["url"], company=it["company"],
                location=it["location"] or "Remote", work_mode="Remote", posted=to_date(it["posted"]),
                salary=it["salary"], description=it["description"][:6000],
                kind="freelance" if contract else "job"))
        log(f"{board}: {len(items)} jobs, {kept} mention crypto/web3")
    return jobs
