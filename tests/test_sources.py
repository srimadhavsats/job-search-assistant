"""Sources parse real-looking responses and survive partial failures (no network)."""
import json

import httpx
import pytest

from tests.conftest import mock_client_factory

WEB3_CAREER_ROW = """<table><tr class="table_row"><td><a href="/support-engineer-acme/123"><h2>Support Engineer</h2></a>
<h3>Acme</h3><span class="job-location-mobile">Remote</span><time datetime="2026-09-24"></time>
<p class="text-salary">$50k</p></td></tr></table>"""


def test_html_list_keeps_other_pages_when_one_times_out(monkeypatch, profile):
    """2026-09-25: one ReadTimeout on web3.career threw away all ~390 jobs of the run."""
    from jobhunter.sources import html_list

    def handler(req):
        if "support-jobs" in str(req.url):
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, text=WEB3_CAREER_ROW)

    monkeypatch.setattr(html_list, "http_client", mock_client_factory(handler, tries=2))
    cfg = {"name": "web3.career", "urls": ["https://web3.career/analyst-jobs", "https://web3.career/support-jobs",
                                           "https://web3.career/community-manager-jobs"],
           "pages": 1, "item": "tr.table_row", "base_url": "https://web3.career",
           "fields": {"title": "h2", "company": "h3", "location": "span.job-location-mobile",
                      "posted": "time@datetime", "salary": "p.text-salary", "link": "a@href"}}
    msgs = []
    jobs = html_list.fetch(cfg, profile, msgs.append)
    assert len(jobs) == 2 and jobs[0].title == "Support Engineer" and jobs[0].company == "Acme"
    assert jobs[0].url == "https://web3.career/support-engineer-acme/123"
    assert any("support-jobs" in m and "WARNING" in m for m in msgs)


def test_html_list_raises_when_every_page_fails(monkeypatch, profile):
    from jobhunter.sources import html_list

    def handler(req):
        raise httpx.ConnectError("down", request=req)

    monkeypatch.setattr(html_list, "http_client", mock_client_factory(handler, tries=1))
    cfg = {"name": "x", "urls": ["https://x.example/a"], "item": "tr", "fields": {"title": "h2", "link": "a@href"}}
    with pytest.raises(RuntimeError):
        html_list.fetch(cfg, profile, lambda m: None)


def test_rss_one_dead_feed_keeps_the_other(monkeypatch, profile):
    from jobhunter.sources import rss
    feed = """<?xml version="1.0"?><rss><channel><item><title>KYC Analyst at Acme</title>
    <link>https://acme.example/kyc</link><description>crypto exchange KYC</description></item></channel></rss>"""

    def handler(req):
        if "dead" in str(req.url):
            raise httpx.ConnectError("down", request=req)
        return httpx.Response(200, text=feed)

    monkeypatch.setattr(rss, "http_client", mock_client_factory(handler, tries=1))
    jobs = rss.fetch({"name": "Feeds", "urls": ["https://dead.example/rss", "https://ok.example/rss"],
                      "company_from": "title_at"}, profile, lambda m: None)
    assert len(jobs) == 1 and jobs[0].title == "KYC Analyst" and jobs[0].company == "Acme"


def test_getro_and_consider(monkeypatch, profile):
    from jobhunter.sources import vc_boards
    getro = {"results": {"count": 2, "jobs": [
        {"title": "Customer Support Specialist", "url": "https://jobs.ashbyhq.com/x/1", "organization": {"name": "Phantom"},
         "locations": ["Remote"], "work_mode": "remote", "created_at": 1790336927},
        {"title": "Old role", "url": "https://x/2", "organization": {"name": "Y"}, "locations": ["NYC"],
         "work_mode": "on_site", "created_at": 1700000000}]}}
    consider = {"jobs": [{"title": "Compliance Analyst", "applyUrl": "https://c/1", "companyName": "Coinbase",
                          "locations": ["Remote - India"], "remote": True, "timeStamp": "2026-09-24T14:55:42Z",
                          "applicationWindow": {"status": "accepting"}, "minYearsExp": 2}], "meta": {}}

    def handler(req):
        if "api.getro.com" in str(req.url):
            assert req.headers["accept"] == "application/json"
            body = json.loads(req.content)
            assert body["hits_per_page"] == 100
            return httpx.Response(200, json=getro)
        if req.url.path == "/jobs":
            return httpx.Response(200, text='<script>{"csrfToken":"tok123"}</script>')
        assert req.headers.get("x-csrf-token") == "tok123"
        return httpx.Response(200, json=consider)

    monkeypatch.setattr(vc_boards, "http_client", mock_client_factory(handler))
    cfg = {"name": "VC job boards", "getro": {"Solana": ["jobs.solana.com", 858]},
           "consider": {"Pantera": ["jobs.panteracapital.com", "pantera-capital"]}}
    jobs = vc_boards.fetch(cfg, {**profile, "max_age_days": 30000}, lambda m: None)
    titles = {j.title for j in jobs}
    assert "Customer Support Specialist" in titles and "Compliance Analyst" in titles
    ca = next(j for j in jobs if j.title == "Compliance Analyst")
    # funds also back fintechs (Veem), so a portfolio listing is a web3 hint, not proof (2026-09-26)
    assert ca.work_mode == "Remote" and ca.experience == "2+ yrs" and ca.web3_hint and not ca.web3_native
    assert ca.source == "VC job boards: Pantera"


def test_himalayas_location_says_who_can_apply():
    from jobhunter.sources.remote_apis import _himalayas_location
    assert _himalayas_location([], []) == "Remote (Worldwide)"
    assert _himalayas_location(["India", "Singapore"], []) == "Remote (India)"
    assert _himalayas_location([], [5.5, 8]) == "Remote (Asia time zones)"
    assert _himalayas_location(["United States"], [-5]) == "Remote (United States only)"


def test_indeed_india_locations():
    from jobhunter.sources.indeed import _clean, _location
    assert _location("Chennai, TN, IN") == "Chennai, Tamil Nadu, India"
    assert _location("TN, IN") == "Tamil Nadu, India"
    assert _location(float("nan")) == ""
    assert _clean(float("nan")) == ""


def test_jobstash_keeps_crypto_only(monkeypatch, profile):
    from jobhunter.sources import jobstash
    data = {"data": [
        {"id": "1", "title": "AML Analyst", "organization": {"name": "eToro", "projects": [{"id": 1}]},
         "location": "Malta", "locationType": "HYBRID", "timestamp": 1790266753442, "url": "https://etoro/1",
         "commitment": "FULL_TIME", "tags": []},
        {"id": "2", "title": "Data Center Foreman", "organization": {"name": "Lambda", "projects": []},
         "location": "Reno", "locationType": "ONSITE", "timestamp": 1790266753442, "url": "https://l/2", "tags": []},
        {"id": "3", "title": "Transaction Monitoring Analyst", "organization": {"name": "Bitfinex", "projects": [{"id": 2}]},
         "location": "Worldwide", "locationType": "REMOTE", "timestamp": 1790266753442, "url": None, "shortUUID": "abc",
         "access": "protected", "commitment": "CONTRACT", "tags": []}]}
    monkeypatch.setattr(jobstash, "http_client", mock_client_factory(lambda req: httpx.Response(200, json=data)))
    jobs = jobstash.fetch({"name": "JobStash", "queries": ["crypto"], "pages": 1}, profile, lambda m: None)
    assert {j.title for j in jobs} == {"AML Analyst", "Transaction Monitoring Analyst"}
    tm = next(j for j in jobs if j.company == "Bitfinex")
    assert tm.kind == "job", "full-time contractor roles are jobs, not gigs"
    assert tm.url == "https://jobstash.xyz/jobs/abc/details" and tm.location.startswith("Remote")


def test_every_source_type_is_registered():
    import yaml
    from jobhunter import sources
    from tests.conftest import ROOT
    for cfg in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
        mod = sources.load(cfg)
        assert hasattr(mod, "fetch"), cfg["name"]
        assert int(cfg.get("every_minutes", 60)) > 0, cfg["name"]
