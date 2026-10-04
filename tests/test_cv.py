"""CV choice, headline cleaning, location lines, referral messages (jobhunter/cv.py)."""
import re

import pytest

from jobhunter import cv
from tests.conftest import ROOT

BANNED = re.compile(r"[;:—–→·]")


@pytest.fixture(scope="module")
def cfg():
    return cv.load_config()


@pytest.mark.parametrize("title,company,source,expect", [
    ("Compliance Analyst (Enhanced Due Diligence)", "Binance", "Company careers: Binance", "tm"),
    ("Transaction Monitoring Analyst", "Bitfinex", "JobStash", "tm"),
    ("Fraud AML Analyst", "Bluecube", "web3.career", "tm"),
    ("Research Analyst, Equity Capital Markets", "Binance", "Company careers: Binance", "research"),
    ("Customer Support Engineer", "Sardine", "CryptocurrencyJobs", "general"),
    ("Community Manager", "Delta Exchange", "LinkedIn", "general"),
    ("Crypto Trainer", "Veer Enterprises", "Apna", "india"),
    ("Customer Support Executive", "CoinDCX", "LinkedIn", "india"),
    ("KYC Analyst", "CoinDCX", "LinkedIn", "tm"),              # TM rule comes first, as in PLAYBOOK section 5
])
def test_pick(cfg, title, company, source, expect):
    assert cv.pick({"Title": title, "Company": company, "Source": source}, cfg) == expect


@pytest.mark.parametrize("title,expect", [
    ("Compliance Analyst (Enhanced Due Diligence) - 12months contract", "Compliance Analyst, Enhanced Due Diligence"),
    ("Senior Data & Business Analyst – Financial Crime & AML", "Data and Business Analyst, Financial Crime and AML"),
    ("Trading Operations Associate (Remote - US time zone)", "Trading Operations Associate"),
    ("Senior QA Engineer /区块链测试工程师", "QA Engineer"),
    ("Transaction Monitoring Analyst - (100% remote Worldwide)", "Transaction Monitoring Analyst"),
    ("Customer support agent", "Customer Support Agent"),
    ("Compliance, International Investigations Associate", "Compliance, Investigations Associate"),
    ("Community Manager, Korea", "Community Manager"),
])
def test_clean_title(sc, title, expect):
    assert cv.clean_title(title, sc) == expect


def test_role_line_has_no_banned_marks(sc, cfg):
    for title in ["Risk & Reg - Transaction Monitoring - Crypto - Senior Associate", "Ops: KYC; AML — Lead",
                  "Web3 Telegram Community Manager — CLOWN Token"]:
        line = cv.role_line(title, cfg["templates"]["tm"], sc)
        assert line and not BANNED.search(line)


@pytest.mark.parametrize("loc,mode,expect", [
    ("Remote", "Remote", "remote work"), ("Bengaluru, Karnataka, India", "", "relocate to Bengaluru"),
    ("Gurgaon", "", "relocate to Gurugram"), ("Dubai, UAE", "", "employer visa sponsorship"),
    ("Your City", "", "Your City, Your State"), ("Singapore", "", "visa sponsorship, or remote"),
])
def test_location_line(sc, cfg, loc, mode, expect):
    line = cv.location_line({"Location": loc, "Work mode": mode}, cfg, sc)
    assert expect in line and not BANNED.search(line)


def test_edit_html_changes_only_headline_and_location():
    html = (ROOT / "CV_Template_Example.html").read_text(encoding="utf-8")
    out = cv._edit_html(html, "SAR Analyst | On-Chain Investigations", "Your City, India (open to relocate to Bengaluru)")
    assert '<div class="role">SAR Analyst | On-Chain Investigations</div>' in out
    assert "<span>Your City, India (open to relocate to Bengaluru)</span>" in out
    strip = lambda h: re.sub(r'<div class="role">.*?</div>|<div class="contact">\s*<span>.*?</span>|<title>.*?</title>', "", h, flags=re.S)
    assert strip(out) == strip(html), "nothing else in the CV may change"


def test_all_templates_are_clean(cfg):
    for tid, t in cfg["templates"].items():
        html = (ROOT / t["html"]).read_text(encoding="utf-8")
        assert cv.visible_banned(html) == [], f"{t['html']} has banned punctuation"


def test_referral_message(cfg):
    msg = cv.referral_message({"Title": "Compliance Analyst – EDD", "Company": "Binance",
                               "Apply link": "https://jobs.lever.co/binance/abc"}, cfg)
    assert "jobs.lever.co/binance/abc" in msg and "https" not in msg
    assert not BANNED.search(msg) and "Binance" in msg and "NAME" in msg


def test_applicable():
    assert cv.applicable({"Flags": ""})
    assert not cv.applicable({"Flags": "Remote but US-only — you likely can't apply from India"})
    assert not cv.applicable({"Link check": "Closed (25 Sep)"})
