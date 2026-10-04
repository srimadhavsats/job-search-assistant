"""Transparent rule-based relevance score. All weights come from config/profile.yaml → scoring."""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from jobhunter.models import Job


@lru_cache(maxsize=None)
def _rx(phrase: str) -> re.Pattern:
    # Whole-word match; a trailing * allows longer words ("investigat*" → investigator).
    phrase = str(phrase).strip().lower()
    prefix = phrase.endswith("*")
    body = re.escape(phrase.rstrip("*"))
    return re.compile(r"(?<![a-z0-9])" + body + ("" if prefix else r"(?![a-z0-9])"))


def _hits(text: str, phrases) -> list[str]:
    return [str(p).rstrip("*") for p in phrases if _rx(p).search(text)]


_WORK_WORDS = re.compile(
    r"\b(remote|hybrid|on-?site|in-?office|full[- ]?time|part[- ]?time|contract|permanent|anywhere|"
    r"worldwide|global|globally|international|multiple|various|locations?|office|home|wfh|"
    r"work from home|emea|apac|latam|amer)\b")

WORK_AUTH = re.compile(r"\b(?:authori[sz]ed|eligible|legally (?:able|permitted|entitled)|right|permission|permit(?:ted)?)"
                       r" to work in (?:the )?(us|u\.s\.?|usa|united states|uk|united kingdom|eu|european union|canada|"
                       r"australia|singapore|germany|france|japan|hong kong|switzerland|ireland|netherlands)\b")

# flag on a VC portfolio listing whose job text never mentions crypto (Veem, 2026-09-26)
PORTFOLIO_NOT_CRYPTO = "Job text never mentions crypto (VC portfolio company, maybe not crypto work)"

_EXP = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)\b", re.I)


def min_years(text: str) -> int | None:
    """Highest "N+ years" requirement in the text ("5+ years Kafka … 3 years AWS" → 5)."""
    found = [int(m.group(1)) for m in _EXP.finditer(text or "") if int(m.group(1)) <= 20]
    return max(found) if found else None


def required_certificate(desc: str, sc: dict) -> str | None:
    """"ACAMS, ACFCS or other certification" in a requirements list, without "preferred" nearby."""
    for m in re.finditer(r"\b(acams|acfcs|cams|cfe|cfcs|ica diploma)\b", desc):
        around = desc[max(0, m.start() - 60):m.end() + 90]
        if not re.search(sc.get("language_optional_words", r"$^") + r"|\bideally\b|\bor equivalent\b|\bwould be\b", around):
            return m.group(1)
    return None


def specialist_years(desc: str, sc: dict) -> tuple[int, str] | None:
    """(years, field) when the text asks 5+ years in a specialism such as AML, sanctions or SOC work."""
    fields = sc.get("specialist_fields", [])
    for m in _EXP.finditer(desc):
        n = int(m.group(1))
        if n < sc.get("specialist_min_years", 5) or n > 20:
            continue
        sentence = desc[m.start():m.end() + 90]
        hit = _hits(sentence, fields)
        if hit:
            return n, hit[0]
    return None


def out_of_reach(title: str, desc: str, sc: dict) -> str | None:
    """Reason a job is out of reach even though its location looks fine, or None.

    "KYC/KYB Analyst - Japanese Speaker", "Client Operations Associate New York", posts that
    require fluent Thai/Arabic/…, and student-only programmes (Binance Accelerator Program,
    ~20 rows) all sat in the apply-now band (2026-09-23).
    """
    unpaid = _hits(title, sc.get("unpaid_title_words", []))
    if unpaid:
        return f"Unpaid ({unpaid[0]}), does not meet the income goal"
    for pattern in sc.get("student_only_patterns", []):
        if re.search(pattern, f"{title} {desc}"):
            return "Students and recent graduates only"
    langs = sc.get("required_languages", [])
    hit = _hits(title, langs)
    if hit:
        return f"Needs {hit[0].title()} speaker"
    for lang in _hits(desc, langs):
        l = re.escape(lang)
        need = re.compile(
            rf"(?:fluen\w*|proficien\w*|native|business[- ]level|written and (?:verbal|spoken)|speak\w*)"
            rf"\s+(?:in\s+)?(?:\w+\s+(?:and|or|&)\s+)?{l}\b|\b{l}\s+(?:\w+\s+)?(?:speak\w*|language|fluency|proficiency)"
            # "bilingual English/Mandarin is required" (Binance EDD analysts, 2026-09-26)
            rf"|bilingual[^.]{{0,30}}\b{l}\b|\b{l}\b[^.]{{0,12}}\b(?:is |are )?(?:required|mandatory|a must)\b")
        for m in need.finditer(desc):
            after = desc[m.end():m.end() + 60]
            if not re.search(sc.get("language_optional_words", r"$^"), after):
                return f"Needs {lang.title()} speaker"
    if not _hits(title, sc["india_or_global_locations"]):
        place = _hits(title, sc.get("title_region_words", []))
        if place:
            return f"Title names {place[0].title()}, likely not open to India"
        # "US MLRO Financial Crimes Officer", "Compliance Analyst (UK)": a bare US/UK only counts at the
        # start, in brackets or at the end, because "Support Engineer (US shift)" is normal in India.
        for pattern in sc.get("title_region_patterns", []):
            m = re.search(pattern, title)
            if m:
                return f"Title is for {m.group(1).upper()} only, likely not open to India"
    # "Must be authorized to work in the United States" (added 2026-09-25): a work permit the owner
    # can't get from India. Ignored when India is named nearby or the text says they hire anywhere.
    if not _hits(desc, sc.get("global_remote_words", [])):
        m = WORK_AUTH.search(desc)
        if m and "india" not in desc[max(0, m.start() - 80):m.end() + 80]:
            return f"Text requires work authorisation in the {m.group(1).upper()}"
    # "To be considered you must reside in one of the following cities: São Paulo…" (Sardine support
    # engineer, listed as plain Remote, 2026-09-26) and "Location: Remote - Brazil". An explicit place
    # requirement wins even when a perk says "work from anywhere" (Sardine's page says both).
    m = re.search(r"\bmust (?:reside|live|be located|be based) in\b[^.]{0,80}", desc)
    if m and not _hits(m.group(0), sc["india_or_global_locations"]):
        return f"Text requires living in {m.group(0).split(' in ', 1)[-1][:40].strip()}"
    m = re.search(r"\blocation\s*:?\s*remote\s*[-(]\s*([a-z .]{2,30})", desc)
    if m and _hits(m.group(1), sc["region_locked_terms"] + sc.get("title_region_words", [])) \
            and not _hits(m.group(1), sc["india_or_global_locations"]):
        return f"Text says remote in {m.group(1).strip().title()} only"
    if not _hits(desc, sc.get("global_remote_words", [])):
        # US-only benefits mean US employment ("benefits: HSA, FSA, 401(k)", DV Trading, 2026-09-26)
        m = re.search(sc.get("us_benefits_pattern", r"$^"), desc)
        if m and "india" not in desc:
            return f"Offers US-only benefits ({m.group(0).strip().upper()}), likely US employment"
    # "Based in the US" as a requirement in the text, with the location field just "Remote"
    # (Wormhole/Sunrise Trading Operations Associate scored 89, 2026-09-24). "We're based in the
    # US" describes the company, and "hire globally" wording overrides it.
    if not _hits(desc, sc.get("global_remote_words", [])):
        for m in re.finditer(sc.get("desc_region_pattern", r"$^"), desc):
            before = desc[max(0, m.start() - 25):m.start()]
            if not re.search(r"\b(?:we|we're|company|team|headquarter\w*|offices?|hq)(?:\s+(?:is|are))?\s*$", before):
                return f"Text requires being {m.group(0).strip()}"
    return None


def score(job: Job, sc: dict, today: date, bands: list | None = None) -> None:
    title = job.title.lower()
    desc = job.description.lower()
    loc = job.location.lower()
    everything = f"{title} {job.company.lower()} {desc}"
    pts, why, flags = 0, [], []
    bands = bands or []

    tier_hit = tier_label = None
    for tier in sorted(sc["title_tiers"], key=lambda t: -t["points"]):
        hit = _hits(title, tier["phrases"])
        if hit:
            pts += tier["points"]
            why.append(f"title {tier['label']}: {hit[0]}")
            tier_hit, tier_label = True, tier["label"]
            break
    if not tier_hit:
        pts += sc.get("no_title_match_penalty", 0)

    off = _hits(title, sc.get("off_target_title_words", []))
    if off:
        pts += sc.get("off_target_penalty", 0)
        why.append(f"off-target: {off[0]}")

    senior = bool(_hits(title, sc["senior_title_words"]))
    if senior:
        pts += sc["senior_title_penalty"]
        why.append("senior title")
    elif _hits(title, sc["junior_title_words"]):
        pts += sc.get("junior_title_points", 10)
        why.append("junior-level")
    if not senior and _hits(title, ["manager"]) and not _hits(title, sc.get("manager_exempt_words", [])):
        pts += sc.get("manager_title_penalty", 0)
        why.append("manager title")

    w3 = _hits(everything, sc["web3_terms"])
    mentions = sum(len(_rx(p).findall(desc)) for p in sc["web3_terms"])
    # Crypto VC portfolio boards also list the fintechs a fund backed (Veem, cross-border payments, scored 80
    # on 2026-09-26 with no crypto word anywhere). The board is only a hint: it counts while there is no job
    # text to check, and job text without a single web3 word overrules it.
    hint_only = job.web3_hint and not job.web3_native and not w3
    portfolio_web3 = hint_only and not desc
    strong_web3 = (job.web3_native or portfolio_web3 or bool(_hits(f"{title} {job.company.lower()}", sc["web3_terms"]))
                   or mentions >= sc.get("web3_strong_mentions", 1))
    if w3 and not strong_web3:
        pts += sc.get("weak_web3_bonus", sc["web3_bonus"])
        why.append(f"web3 mentioned only {mentions}x ({', '.join(w3[:2])})")
    elif job.web3_native or w3 or portfolio_web3:
        pts += sc["web3_bonus"]
        why.append("web3" + (f" ({', '.join(w3[:3])})" if w3 else " (crypto VC portfolio)" if portfolio_web3 else ""))
    elif hint_only:
        pts += sc.get("weak_web3_bonus", sc["web3_bonus"])
        why.append("crypto VC portfolio company")
        flags.append(PORTFOLIO_NOT_CRYPTO)
    else:
        pts += sc["not_web3_penalty"] if desc else sc["not_web3_penalty_no_desc"]
        why.append("no web3 words" if desc else "no web3 words in title (no description)")

    skills = _hits(everything, sc["skills"])
    if skills:
        pts += min(len(skills) * sc["skill_points_each"], sc["skill_points_max"])
        why.append("skills: " + ", ".join(skills[:6]))

    remote = job.work_mode == "Remote" or bool(_rx("remote").search(loc))
    good = _hits(loc, sc["india_or_global_locations"])
    # A remote job that still names a place ("Remote - USA", "Denver, CO", "Estonia") is almost
    # always tied to that place. Rather than listing every country, strip the words that mean
    # "anywhere" and see whether a place name is left.
    place = re.sub(r"[^a-z ]+", " ", _WORK_WORDS.sub(" ", loc))
    named_place = bool(re.search(r"[a-z]{2,}", place))
    locked = _hits(loc, sc["region_locked_terms"]) or ([place.split()[0]] if named_place else [])
    # a structured "Remote (South Africa only)" from Himalayas or Jobicy beats a "work from anywhere" line
    hires_globally = bool(_hits(desc, sc.get("global_remote_words", []))) and not re.search(r"\bonly\b", loc)
    # visa wording only counts in the job text: "Compliance Associate, Bank Sponsorship" (Rain, New York)
    # is about sponsor banks and scored 77 as if it offered a visa (2026-09-25)
    visa_ok = bool(_hits(desc, sc["visa_terms"])) and not any(
        re.search(p, desc) for p in sc.get("visa_negative_patterns", []))
    visa_ok = visa_ok or bool(_hits(loc, sc.get("visa_typical_locations", [])))
    region_locked = False
    if good:
        pts += sc["location_points"]
        why.append(f"location: {good[0]}")
    elif remote and not named_place:
        pts += sc["remote_open_points"]
        why.append("remote")
    elif remote and visa_ok:
        pts += sc["abroad_visa_points"]
        why.append("region-listed, but visa is sponsored/mentioned")
    elif remote and hires_globally:
        pts += sc["remote_open_points"]
        why.append(f"listed {locked[0]} but the text says they hire globally")
    elif remote:
        pts += sc["remote_locked_points"]
        region_locked = True
        flags.append(f"Remote but {locked[0].upper()}-only — you likely can't apply from India")
    elif job.location:
        if visa_ok:
            pts += sc["abroad_visa_points"]
            why.append("abroad + visa sponsored/mentioned")
        else:
            region_locked = True
            flags.append("Abroad on-site, no visa/relocation mentioned")

    if _hits(title, ["intern", "internship"]) and "Internship" not in " ".join(flags):
        flags.append("Internship (often for students, check before applying)")
    locale = out_of_reach(title, desc, sc)
    # internships abroad are for local students (Bybit Operations Intern, Abu Dhabi, scored 81 on 2026-09-25)
    if not locale and not good and not remote and _hits(title, ["intern", "internship", "interns", "trainee"]):
        locale = "Internship abroad, these are usually for local students"
    if locale and locale.startswith("Text requires") and good:
        locale = None  # an India-located job whose text says "reporting to a manager based in the US"
    if locale:
        pts += sc.get("locale_lock_points", 0)
        region_locked = True
        flags.append(locale)

    years = min_years(job.experience) if job.experience else None
    if years is None:
        years = min_years(desc)
    if years is not None:
        if years <= sc["exp_ok_max_min_years"]:
            pts += sc["exp_ok_points"]
            why.append(f"exp {years}+ yrs ok")
        elif years >= sc["exp_too_high_min_years"]:
            pts += sc["exp_too_high_penalty"]
            why.append(f"asks {years}+ yrs")
        tech_role = tier_label == "C" or (
            _hits(title, sc.get("tech_role_words", [])) and not _hits(title, sc.get("tech_role_exempt_words", [])))
        if tech_role:  # developer / DevOps / infra title
            if years <= sc.get("dev_entry_max_years", -1) and not senior:
                pts += sc.get("dev_entry_points", 0)
                why.append("entry-level dev role")
            elif years >= sc.get("dev_too_senior_min_years", 99):
                pts += sc.get("dev_too_senior_penalty", 0)
                why.append(f"dev role asks {years}+ yrs")
        if not job.experience:
            job.experience = f"{years}+ yrs"

    # PLAYBOOK section 5: skip when a paid certificate is REQUIRED (preferred is fine).
    cert = required_certificate(desc, sc)
    if cert:
        pts += sc.get("required_cert_points", 0)
        region_locked = True        # capped like other jobs you can't realistically get
        flags.append(f"Requires {cert.upper()} certificate")
    # "5+ years of sanctions compliance", "5+ years of investigations including filing SARs": years in
    # that exact specialism, which the owner does not have (his 5 years are QA and policy review).
    spec = specialist_years(desc, sc)
    if spec:
        pts += sc.get("specialist_years_points", 0)
        flags.append(f"Asks {spec[0]}+ yrs of {spec[1]} experience")
    gaps = _hits(desc, sc.get("missing_skills", []))
    if gaps:
        pts += max(len(gaps) * sc.get("missing_skill_points_each", 0), sc.get("missing_skill_points_max", 0))
        flags.append("Gap: " + ", ".join(gaps[:6]))

    age = (today - job.posted).days if job.posted else None
    if age is not None and age <= sc["fresh_days"]:
        pts += sc["fresh_points"]
        why.append("fresh")
    elif age is not None and age >= sc.get("very_stale_days", 10**6):
        pts += sc.get("very_stale_penalty", 0)
        flags.append(f"Old post ({job.posted.year}) — may be stale/evergreen")
    elif age is not None and age >= sc.get("stale_days", 10**6):
        pts += sc.get("stale_penalty", 0)
        flags.append(f"Posted {age // 30} months ago")
    if job.web3_native or (job.web3_hint and strong_web3):
        pts += sc["web3_source_points"]

    scam = _hits(everything, sc["scam_terms"])
    if scam:
        flags.append(f"⚠ SCAM? ({scam[0]})")

    if region_locked:
        pts = min(pts, sc.get("region_locked_max_score", 100))
    if len(gaps) >= sc.get("many_gaps", 99):
        pts = min(pts, sc.get("many_gaps_max_score", 100))
    if not (job.web3_native or job.web3_hint or w3):
        pts = min(pts, sc.get("not_web3_max_score", 100))
    elif not strong_web3:
        pts = min(pts, sc.get("weak_web3_max_score", 100))
    job.score = max(0, min(100, pts))
    job.why = " | ".join(why)
    job.priority = next((b["label"] for b in bands if job.score >= b["min"]), "")
    job.flags = "; ".join(flags)


_MONEY = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(?:usd|usdc|usdt|usdg|\$)?", re.I)


def reward_usd(text: str, inr_markers=(), inr_rate: float = 90) -> float | None:
    """Best-effort largest amount in a reward/budget string ("$250", "5002 USDG", "$1k-2k").

    Indian listings quote rupees ("4-5.5 Lacs PA"), which are converted so they aren't read as USD.
    """
    if not text or not re.search(r"\d", text):
        return None
    low = text.lower()
    rupees = any(m in low for m in inr_markers)
    if "lac" in low or "lakh" in low:  # 1 lakh = 100,000
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)?\s*(\d+(?:\.\d+)?)?\s*lac|lakh", low)
        if m:
            value = float(m.group(2) or m.group(1)) * 100_000
            return value / inr_rate
    amounts = []
    for m in _MONEY.finditer(text):
        try:
            v = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        except ValueError:
            continue
        if 0 < v < 10_000_000:
            amounts.append(v)
    if not amounts:
        return None
    return max(amounts) / (inr_rate if rupees else 1)


def is_freelance(job: Job, words) -> bool:
    return job.kind == "freelance" or bool(_hits(f"{job.title} {job.experience}".lower(), words))


def score_freelance(job: Job, fsc: dict, sc: dict, today: date, bands: list | None = None) -> None:
    """Freelance/bounty score: can you do it, is it crypto, does it pay, and how soon."""
    title = job.title.lower()
    desc = job.description.lower()
    everything = f"{title} {job.company.lower()} {desc}"
    pts, why, flags = 0, [], []

    # A task word in the title is worth full points. Found only in the gig text ("support", "test" and
    # "data" appear in almost every description) it is worth less: Freelancer.com build and marketing
    # gigs scored 83 that way (2026-09-25).
    best = None
    for tier in sorted(fsc["task_tiers"], key=lambda t: -t["points"]):
        hit = _hits(title, tier["phrases"])
        if hit:
            best = (tier["points"], f"task {tier['label']}: {hit[0]}")
            break
    if best is None:
        for tier in sorted(fsc["task_tiers"], key=lambda t: -t["points"]):
            hit = _hits(desc[:400], tier["phrases"])
            if hit:
                best = (tier["points"] - fsc.get("desc_only_task_penalty", 15), f"task {tier['label']} (text only): {hit[0]}")
                break
    if best:
        pts += best[0]
        why.append(best[1])
    else:
        pts += fsc.get("no_task_match_penalty", 0)
    off = _hits(title, fsc.get("off_task_words", []))
    if off:
        pts += fsc["off_task_penalty"]
        why.append(f"off-skill: {off[0]}")

    w3 = _hits(everything, sc["web3_terms"])
    if job.web3_native or job.web3_hint or w3:
        pts += sc["web3_bonus"]
        why.append("web3")
    else:
        pts += sc["not_web3_penalty"] // 2
        why.append("not clearly web3")

    skills = _hits(everything, sc["skills"])
    if skills:
        pts += min(len(skills) * sc["skill_points_each"], sc["skill_points_max"])
        why.append("skills: " + ", ".join(skills[:5]))

    usd = reward_usd(job.salary, tuple(fsc.get("inr_markers", ())), fsc.get("inr_to_usd", 90))
    band = next((b for b in fsc["pay_bands"] if usd is not None and usd >= b["min"]), None)
    if band:
        pts += band["points"]
        why.append(f"pays ~${usd:,.0f}")
    else:
        pts += fsc.get("no_pay_listed_penalty", 0)

    loc = job.location.lower()
    if _hits(loc, sc["region_locked_terms"]) and not _hits(loc, sc["india_or_global_locations"]):
        pts -= 25
        flags.append(f"Region-limited ({job.location[:30]})?")
    else:
        pts += 10

    if job.deadline:
        days_left = (job.deadline - today).days
        lo, hi = fsc["deadline_sweet_spot"]
        if days_left <= 1:
            pts += fsc["deadline_tight_penalty"]
            flags.append("Closes within 24h")
        elif lo <= days_left <= hi:
            pts += fsc["deadline_points"]
            why.append(f"{days_left} days left")
        else:
            why.append(f"{days_left} days left")
    if job.posted and (today - job.posted).days <= fsc["fresh_days"]:
        pts += fsc["fresh_points"]
        why.append("just posted")

    subs = re.search(r"(\d+) submissions", job.experience or "")
    if subs and int(subs.group(1)) >= fsc["crowded_submissions"]:
        pts += fsc["crowded_penalty"]
        why.append(f"crowded ({subs.group(1)} submissions)")

    for pattern in fsc.get("region_lock_patterns", []):
        m = re.search(pattern, f"{title} {desc}", re.I)
        if m and not any(w in m.group(0).lower() for w in fsc.get("region_lock_ok_words", [])):
            pts += fsc.get("region_lock_penalty", -45)
            flags.append(f"Country-locked: {m.group(0).strip()[:50]}")
            break

    illegal = _hits(f"{title} {desc[:800]}", fsc.get("illegal_gig_terms", []))
    if illegal:
        pts += fsc.get("illegal_gig_penalty", -60)
        flags.append(f"⛔ ILLEGAL/IDENTITY RENTAL ({illegal[0]}) — do not touch")

    capital = _hits(f"{title} {desc[:300]}", fsc.get("needs_capital_terms", []))
    if capital:
        pts += fsc["needs_capital_penalty"]
        flags.append(f"May need your own money ({capital[0]})")
    scam = _hits(everything, sc["scam_terms"])
    if scam:
        flags.append(f"⚠ SCAM? ({scam[0]})")

    if not (job.web3_native or job.web3_hint or w3):  # non-crypto gigs never rank above the "maybe" band
        pts = min(pts, sc.get("not_web3_max_score", 30))
    job.score = max(0, min(100, pts))
    job.why = " | ".join(why)
    job.flags = "; ".join(flags)
    job.priority = next((b["label"] for b in bands or [] if job.score >= b["min"]), "")
