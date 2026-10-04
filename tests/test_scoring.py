"""Scoring regressions: every case below was a real wrong result once (see handoff.md dated entries)."""
from datetime import date, timedelta

import pytest

from jobhunter.models import Job
from jobhunter.scoring import out_of_reach, score, score_freelance

TODAY = date(2026, 9, 25)


def s(sc, profile, **kw):
    kw.setdefault("source", "test")
    kw.setdefault("url", "https://example.org/job")
    job = Job(**kw)
    score(job, sc, TODAY, profile["priority_bands"])
    return job


def test_remote_usa_is_capped(sc, profile):
    j = s(sc, profile, title="Customer Support Specialist", company="Coinbase", location="Remote - USA",
          work_mode="Remote", description="crypto exchange support", web3_native=True)
    assert j.score <= sc["region_locked_max_score"] and "can't apply from India" in j.flags


def test_bengaluru_support_is_good(sc, profile):
    j = s(sc, profile, title="Customer Support Specialist", company="CoinDCX", location="Bengaluru, India",
          description="crypto exchange support 2+ years", web3_native=True, posted=TODAY)
    assert j.score >= 70


def test_based_in_the_us_in_text(sc, profile):
    """Wormhole Trading Operations Associate scored 89 with location Remote (2026-09-24)."""
    j = s(sc, profile, title="Trading Operations Associate", company="Wormhole", location="Remote", work_mode="Remote",
          description="crypto trading operations. Requirements: Based in the US", web3_native=True)
    assert j.score <= sc["region_locked_max_score"]


def test_work_authorisation_in_text(sc, profile):
    j = s(sc, profile, title="Support Engineer", company="Acme", location="Remote", work_mode="Remote",
          description="crypto wallet support. You must be authorized to work in the United States.", web3_native=True)
    assert j.score <= sc["region_locked_max_score"] and "work authorisation" in j.flags


def test_work_authorisation_ignored_when_india_allowed(sc):
    assert out_of_reach("analyst", "must be eligible to work in india or the uk", sc) is None
    assert out_of_reach("analyst", "we hire globally. must be authorized to work in the us", sc) is None


@pytest.mark.parametrize("title,desc,expect", [
    ("KYC Analyst - Japanese Speaker", "", "Japanese"),
    ("Community Manager", "you are fluent in Thai and English", "Thai"),
    ("Binance Accelerator Program - Operations", "current university students and recent graduates", "Students"),
    ("Investigative Journalist (Volunteer)", "", "Unpaid"),
    ("Client Operations Associate New York", "", "New York"),
])
def test_out_of_reach(sc, title, desc, expect):
    assert expect.lower() in (out_of_reach(title.lower(), desc.lower(), sc) or "").lower()


def test_spanish_preferred_is_fine(sc):
    assert out_of_reach("support analyst", "spanish speaker preferred", sc) is None


def test_global_remote_company_is_not_hires_globally(sc, profile):
    """QuickNode (US and Portugal only) was #1 at 87 on 'global remote company' (2026-09-25)."""
    j = s(sc, profile, title="Technical Support Engineer", company="QuickNode", location="United States; Portugal",
          work_mode="Remote", description="We are a global remote company with offices in Fort Lauderdale", web3_native=True)
    assert j.score <= sc["region_locked_max_score"]


def test_mexico_city_listing_bengaluru_office_stays_capped(sc, profile):
    """Stripe KYB Associate in Mexico City scored 84 because its text listed Bengaluru (2026-09-20)."""
    j = s(sc, profile, title="KYB Operations Associate", company="Stripe", location="Mexico City",
          description="crypto KYB. Offices in Bengaluru, India, Dublin", web3_native=False)
    assert j.score <= sc["region_locked_max_score"]


def test_gulf_counts_as_visa_sponsored(sc, profile):
    j = s(sc, profile, title="Compliance Analyst", company="Bybit", location="Dubai, UAE",
          description="crypto exchange AML analyst 2 years", web3_native=True)
    assert "Abroad on-site" not in j.flags and j.score > sc["region_locked_max_score"]


def test_senior_devops_with_many_gaps_is_capped(sc, profile):
    j = s(sc, profile, title="DevOps Engineer", company="Binance", location="Asia", work_mode="Remote",
          description="5+ years kafka redis kubernetes terraform ansible in production crypto", web3_native=True)
    assert j.score <= 50


def test_not_web3_is_capped(sc, profile):
    j = s(sc, profile, title="Customer Support Specialist", company="Some BPO", location="Noida, India",
          description="voice process for a telecom client, rotational shifts")
    assert j.score <= sc["not_web3_max_score"]


def test_old_evergreen_post_is_penalised(sc, profile):
    fresh = s(sc, profile, title="Support Engineer", company="Crypto.com", location="Bangalore",
              description="crypto", web3_native=True, posted=TODAY)
    old = s(sc, profile, title="Support Engineer", company="Crypto.com", location="Bangalore",
            description="crypto", web3_native=True, posted=TODAY - timedelta(days=500))
    assert old.score < fresh.score and "Old post" in old.flags


def test_flash_bitcoin_gig_is_flagged_as_scam(sc, profile):
    job = Job(source="Freelancer", title="Flash Bitcoin Generator Webapp", url="https://f/1", kind="freelance",
              description="build a flash bitcoin generator for crypto wallets", salary="500 USD")
    score_freelance(job, profile["freelance_scoring"], sc, TODAY, profile["priority_bands"])
    assert "SCAM" in job.flags


def test_identity_rental_gig_is_killed(sc, profile):
    job = Job(source="Telegram", title="Need US man for account verification", url="https://t/1", kind="freelance",
              description="crypto exchange account verification in your name, pay 50 usdt")
    score_freelance(job, profile["freelance_scoring"], sc, TODAY, profile["priority_bands"])
    assert "⛔" in job.flags


# ---- found in the first full run of the new system (2026-09-25) ----
def test_sponsorship_in_title_is_not_a_visa(sc, profile):
    j = s(sc, profile, title="Compliance Associate - Bank Sponsorship & Product Expansion", company="Rain",
          location="New York, NY", description="stablecoin card compliance, 4+ years", web3_native=True)
    assert j.score <= sc["region_locked_max_score"]


def test_structured_country_lock_beats_work_from_anywhere(sc, profile):
    j = s(sc, profile, title="Crypto Research Analyst", company="Crypto Banter", location="Remote (South Africa only)",
          work_mode="Remote", description="crypto research, work from anywhere", web3_native=True)
    assert j.score <= sc["region_locked_max_score"]


def test_us_prefix_in_title(sc, profile):
    j = s(sc, profile, title="US MLRO Financial Crimes Officer", company="Copper", location="Remote", work_mode="Remote",
          description="crypto custody AML", web3_native=True)
    assert j.score <= sc["region_locked_max_score"] and "Title is for US" in j.flags
    ok = s(sc, profile, title="Support Engineer (US shift)", company="CoinDCX", location="Bengaluru, India",
           description="crypto support", web3_native=True)
    assert ok.score > sc["region_locked_max_score"]


def test_internship_abroad(sc, profile):
    j = s(sc, profile, title="Operations Intern (Bybit Card)", company="Bybit", location="Abu Dhabi, UAE",
          description="crypto card operations", web3_native=True)
    assert j.score <= sc["region_locked_max_score"] and "Internship abroad" in j.flags


def test_freelance_dev_gig_with_support_in_text_is_not_top(sc, profile):
    job = Job(source="Freelancer", title="Kaspa-Based Credential Verification MVP", url="https://f/2", kind="freelance",
              description="we need support building a blockchain credential verification MVP", salary="250-750 USD",
              posted=TODAY)
    score_freelance(job, profile["freelance_scoring"], sc, TODAY, profile["priority_bands"])
    assert job.score < 55


def test_freelance_research_gig_still_scores(sc, profile):
    job = Job(source="Superteam", title="Explain Market Tokenization in Your Country", url="https://f/3", kind="freelance",
              description="write a crypto research thread", salary="500 USDC", web3_native=True, posted=TODAY)
    score_freelance(job, profile["freelance_scoring"], sc, TODAY, profile["priority_bands"])
    assert job.score >= 70


# Quick Heal "Junior Consultant" (Indeed, 2026-09-26) scored 86 and was #2 in the queue. The job is a digital
# forensics trainer: crypto forensics is 1 topic of 11 and the must-haves are device and malware forensics tools.
QUICK_HEAL = ("We are seeking a Digital Forensics and Cyber Investigation Trainer. The ideal candidate has a strong "
              "background in digital forensics, malware analysis, network investigations and emerging technologies "
              "such as IoT, cloud and cryptocurrencies. Advanced Malware Analysis. Forensic Scripting (Python). "
              "Advanced Mobile Forensics (including JTAG and chip-off techniques). Cloud Forensics (AWS). "
              "Cryptocurrency Forensics (blockchain tracing, wallet forensics). Network Forensics and CDR Analysis. "
              "Audio/Video Forensics and CCTV Footage Analysis. Expertise in using and teaching commercial forensic "
              "tools (Cellebrite, EnCase, Magnet, Oxygen, X-Ways). In-depth understanding of blockchain analysis tools "
              "(e.g., Chainalysis, CipherTrace). 2+ years of experience in hands-on forensics.")


def test_forensics_trainer_with_crypto_as_one_topic_leaves_the_queue(sc, profile):
    j = s(sc, profile, title="Junior Consultant", company="Quick Heal", location="Maharashtra, India",
          description=QUICK_HEAL, posted=TODAY)
    assert j.score < 55, j.why                     # the Apply Queue starts at 55
    assert "cellebrite" in j.flags.lower()         # the gap is shown, so the reason is visible in the sheet


def test_crypto_tracing_consultant_still_scores(sc, profile):
    j = s(sc, profile, title="Junior Consultant", company="Quick Heal", location="Maharashtra, India",
          description="Support crypto scam investigations with blockchain tracing of wallet flows to exchanges "
                      "using Chainalysis. Write reports on on-chain fund flows. 2+ years in fraud or AML.", posted=TODAY)
    assert j.score >= 70, j.why


# Veem "Offshore Technical Support & API Implementation Specialist" (VC job boards: Pantera, 2026-09-26) scored 80.
# Veem is a cross-border payments company, and portfolio boards list every company a fund backed.
VEEM = dict(title="Offshore Technical Support & API Implementation Specialist", company="Veem", location="India",
            posted=TODAY, web3_hint=True, source="VC job boards: Pantera")


def test_vc_portfolio_listing_without_text_still_counts_as_crypto(sc, profile):
    j = s(sc, profile, **VEEM)
    assert j.score >= 55 and "crypto VC portfolio" in j.why


def test_vc_portfolio_job_text_without_crypto_is_capped(sc, profile):
    from jobhunter.scoring import PORTFOLIO_NOT_CRYPTO
    j = s(sc, profile, **VEEM, description="Veem transforms cross-border payments with global payments and FX "
          "tools. 3+ years in API implementation, REST APIs, JSON, OAuth, webhooks, Postman. Customer support by "
          "phone, email and chat. Fintech or payments experience preferred.")
    assert j.score <= sc["weak_web3_max_score"] and PORTFOLIO_NOT_CRYPTO in j.flags


def test_vc_portfolio_job_text_with_crypto_keeps_its_score(sc, profile):
    j = s(sc, profile, **VEEM, description="Support stablecoin payouts and on-chain settlement for our crypto "
          "customers. Help exchanges and wallets integrate our blockchain APIs. 3+ years of technical support.")
    assert j.score >= 55 and "never mentions crypto" not in j.flags
