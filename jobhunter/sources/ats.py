"""Company career boards on Greenhouse, Lever, Ashby, Workable, SmartRecruiters and Recruitee
(public JSON APIs, no scraping). The last three were added 2026-09-25 when ~200 more crypto
companies were checked for public boards.

Config:
  companies:
    Company Name: [greenhouse|lever|ashby|workable|smartrecruiters|recruitee, board-slug]
"""
from concurrent.futures import ThreadPoolExecutor

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, html_to_text, http_client, to_date


def _greenhouse(client, company, slug):
    data = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true").json()
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name", "")
        desc = html_to_text(j.get("content"))
        yield Job(source="", title=j["title"], url=j["absolute_url"], company=company, location=location,
                  work_mode=detect_work_mode(j["title"], location),
                  posted=to_date(j.get("first_published") or j.get("updated_at")), description=desc)


def _lever(client, company, slug):
    for j in client.get(f"https://api.lever.co/v0/postings/{slug}?mode=json").json():
        cats = j.get("categories") or {}
        location = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        wt = (j.get("workplaceType") or "").replace("onsite", "Onsite").replace("remote", "Remote").replace("hybrid", "Hybrid")
        sal = j.get("salaryRange") or {}
        salary = f"{sal.get('currency', '')} {sal.get('min', '')}-{sal.get('max', '')}".strip() if sal else ""
        desc = " ".join(filter(None, [j.get("descriptionPlain"), j.get("additionalPlain"),
                                      html_to_text(" ".join(l.get("content", "") for l in j.get("lists") or []))]))
        yield Job(source="", title=j["text"], url=j["hostedUrl"], company=company, location=location,
                  work_mode=wt if wt in ("Onsite", "Remote", "Hybrid") else detect_work_mode(j["text"], location),
                  posted=to_date(j.get("createdAt")), salary=salary, description=desc[:6000])


def _ashby(client, company, slug):
    data = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true").json()
    for j in data.get("jobs", []):
        if not j.get("isListed", True):
            continue
        locs = [j.get("location", "")] + [l.get("location", "") for l in j.get("secondaryLocations") or []]
        location = ", ".join(x for x in locs if x)
        wt = j.get("workplaceType") or ("Remote" if j.get("isRemote") else "")
        salary = ((j.get("compensation") or {}).get("compensationTierSummary") or "")
        yield Job(source="", title=j["title"], url=j["jobUrl"], company=company, location=location,
                  work_mode={"OnSite": "Onsite"}.get(wt, wt), posted=to_date(j.get("publishedAt")),
                  salary=salary, description=(j.get("descriptionPlain") or "")[:6000])


def _workable(client, company, slug):
    data = client.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"}).json()
    for j in data.get("jobs", []):
        location = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        remote = j.get("telecommuting") in (True, "true")
        yield Job(source="", title=j.get("title", ""), url=j.get("url") or j.get("shortlink", ""), company=company,
                  location=("Remote, " + location) if remote else location,
                  work_mode="Remote" if remote else detect_work_mode(j.get("title", ""), location),
                  posted=to_date(j.get("published_on") or j.get("created_at")),
                  description=html_to_text(j.get("description")))


def _smartrecruiters(client, company, slug):
    data = client.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 100}).json()
    for j in data.get("content", []):
        loc = j.get("location") or {}
        location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country", "").upper()]))
        remote = bool(loc.get("remote"))
        yield Job(source="", title=j.get("name", ""),
                  url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", company=company,
                  location=("Remote, " + location) if remote else location,
                  work_mode="Remote" if remote else ("Hybrid" if loc.get("hybrid") else ""),
                  posted=to_date(j.get("releasedDate")),
                  experience=(j.get("experienceLevel") or {}).get("label", ""))


def _recruitee(client, company, slug):
    data = client.get(f"https://{slug}.recruitee.com/api/offers/").json()
    for j in data.get("offers", []):
        location = j.get("location") or ", ".join(filter(None, [j.get("city"), j.get("country")]))
        remote = bool(j.get("remote"))
        yield Job(source="", title=j.get("title", ""), url=j.get("careers_url") or j.get("careers_apply_url", ""),
                  company=company, location=("Remote, " + location) if remote else location,
                  work_mode="Remote" if remote else ("Hybrid" if j.get("hybrid") else detect_work_mode(location)),
                  posted=to_date(j.get("published_at") or j.get("created_at")),
                  description=html_to_text(" ".join(filter(None, [j.get("description"), j.get("requirements")]))))


ADAPTERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "workable": _workable,
            "smartrecruiters": _smartrecruiters, "recruitee": _recruitee}


def fetch(cfg, profile, log):
    jobs = []

    def one(item):
        company, (ats, slug) = item
        for attempt in (1, 2):  # careers APIs occasionally time out; one retry clears most of those
            try:
                with http_client() as client:
                    found = list(ADAPTERS[ats](client, company, slug))
                log(f"{company} ({ats}) → {len(found)} open jobs")
                return found
            except Exception as e:  # one broken company must not stop the others
                if attempt == 2:
                    log(f"{company} ({ats}/{slug}) FAILED: {e!r}"[:200])
        return []

    with ThreadPoolExecutor(max_workers=10) as pool:
        for found in pool.map(one, (cfg.get("companies") or {}).items()):
            for job in found:
                job.source = cfg["name"] + ": " + job.company
                job.web3_native = cfg.get("web3_native", False)
                jobs.append(job)
    return jobs
