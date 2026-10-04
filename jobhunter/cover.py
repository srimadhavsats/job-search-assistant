"""Job-specific cover letters and form answers (added 2026-09-26).

For every job in the Apply Queue a cover letter is built from config/cover_letters.yaml: an opening for the
job family (TM and AML, research, support and everything else), the two or three evidence paragraphs whose
trigger words appear most in that job's text, an honest gap paragraph when the job asks for something the
owner has not done at work, a location line that fits the job, and a closing. Every sentence comes from the
CVs and the letters already sent, so nothing is invented. It is rendered to PDF in the same style as the
hand-written letters, and a .txt copy holds the letter plus ready form answers (PLAYBOOK section 10) with
the expected pay for that kind of employer.

The "Cover letter" column says "(asked for)" when the job text mentions a cover or motivation letter.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import re
from datetime import date
from pathlib import Path

import yaml

from jobhunter import cv
from jobhunter.scoring import _hits

ROOT = Path(__file__).resolve().parent.parent
ASKED = re.compile(r"\b(cover(?:ing)? letter|motivation(?:al)? letter|letter of motivation|why (?:do )?you want to (?:join|work))\b", re.I)

STYLE = """
  @page { size: A4; margin: 15mm 17mm; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: "Segoe UI", -apple-system, Arial, sans-serif; font-size: 10.2pt; line-height: 1.52; color: #1a1f2b; }
  .head { border-bottom: 2.5px solid #f7931a; padding-bottom: 7pt; margin-bottom: 12pt; }
  .head h1 { font-size: 19pt; font-weight: 800; letter-spacing: 0.5px; }
  .head .role { font-size: 10pt; color: #b26505; font-weight: 600; margin: 2pt 0 4pt; }
  .head .contact { font-size: 8.6pt; color: #444c5c; }
  .sep { color: #f7931a; padding: 0 3pt; }
  .date { font-size: 9pt; color: #555e70; margin-bottom: 10pt; }
  p { margin-bottom: 9pt; }
  .sig { margin-top: 12pt; }
  a.cvlink { color: inherit; text-decoration: none; }
"""


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "cover_letters.yaml").read_text(encoding="utf-8"))


def me(ccfg: dict) -> dict:
    """Who the letters are from (config/cover_letters.yaml, candidate)."""
    return ccfg.get("candidate") or {}


def asked_for(text: str) -> bool:
    return bool(ASKED.search(text or ""))


def _city(row: dict) -> str | None:
    low = str(row.get("Location") or "").lower()
    for c in ["Bengaluru", "Bangalore", "Mumbai", "Gurugram", "Gurgaon", "Noida", "New Delhi", "Delhi", "Hyderabad",
              "Pune", "Chennai", "Kolkata", "Ahmedabad", "Jaipur", "Gandhinagar", "Kochi", "Chandigarh"]:
        if c.lower() in low:
            return {"Bangalore": "Bengaluru", "Gurgaon": "Gurugram"}.get(c, c)
    return None


def logistics(row: dict, ccfg: dict, sc: dict) -> str:
    lines = ccfg["logistics"]
    low = str(row.get("Location") or "").lower()
    remote = str(row.get("Work mode") or "") == "Remote" or any(w in low for w in ("remote", "anywhere", "worldwide"))
    if remote or not low:
        return lines["remote"]
    city = _city(row)
    if city:
        return lines["india_city"].format(city=city)
    home = str(me(ccfg).get("home_city") or "").lower()
    if "india" in low or (home and home in low):
        return lines["india"]
    return lines["abroad"]


def expected_pay(row: dict, ccfg: dict) -> str:
    pay = ccfg["expected_pay"]
    company = str(row.get("Company") or "").lower()
    low = str(row.get("Location") or "").lower()
    if row.get("_kind") == "freelance":
        return pay["gig"]
    level = "analyst" if _hits(str(row.get("Title") or "").lower(), ccfg.get("analyst_words", [])) else "entry"
    if _hits(company, ccfg.get("indian_companies", [])) or str(row.get("Source") or "") in ("Naukri", "Apna"):
        return pay[f"indian_{level}"]
    if "india" in low or _city(row):          # a global company hiring in India (office or "Remote - India")
        return pay[f"global_{level}"]
    return pay["remote_global"]


def pick_evidence(family: str, text: str, ccfg: dict, n: int = 3) -> list[dict]:
    fam = family if family in ("tm", "research") else "general" if family == "general" else "india"
    scored = []
    for i, ev in enumerate(ccfg["evidence"]):
        if fam not in ev.get("families", []) and not (fam == "india" and "general" in ev.get("families", [])):
            continue
        hits = len(_hits(text, ev["triggers"]))
        scored.append((hits, -i, ev))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    anchor = (ccfg.get("anchors") or {}).get(family)
    chosen = [ev for _, _, ev in scored if ev["id"] == anchor][:1]
    chosen += [ev for hits, _, ev in scored if hits > 0 and ev not in chosen][: n - len(chosen)]
    if len(chosen) < 2:   # little or no job text: the family's first two pieces
        chosen += [ev for _, _, ev in sorted(scored, key=lambda t: t[1], reverse=True) if ev not in chosen][: 2 - len(chosen)]
    return chosen


def compose(row: dict, text: str, sc: dict, ccfg: dict | None = None, cvcfg: dict | None = None) -> dict:
    """The letter as paragraphs plus header fields. Pure function (no files), so it can be tested."""
    ccfg, cvcfg = ccfg or load_config(), cvcfg or cv.load_config()
    family = cv.pick(row, cvcfg)
    family = family if family in ccfg["openings"] else "general"
    role = cv.clean_title(str(row.get("Title") or ""), sc) or "open"
    company = cv.BANNED.sub(" ", str(row.get("Company") or "your team")).strip() or "your team"
    low = (text or "").lower()
    paras = [ccfg["openings"][family].format(role=role, company=company)]
    for ev in pick_evidence(family, low, ccfg):
        paras.append(f"<b>{htmllib.escape(ev['lead'])}</b> {ev['text']}")
    for gap, words in ccfg.get("gap_triggers", {}).items():
        if (gap == family or (gap == "qa" and _hits(str(row.get("Title") or "").lower(), ["qa", "quality", "test", "sdet"])))\
                and _hits(low, words):
            paras.append(f"<b>I want to be direct about the gap.</b> {ccfg['gaps'][gap]}")
            break
    paras.append(logistics(row, ccfg, sc))
    paras.append(ccfg["closing"].get(family, ccfg["closing"]["general"]))
    where = str(row.get("Location") or "").strip()
    header = f"Application for {role}" + (f" ({cv.BANNED.sub(' ', where)[:40].strip()})" if where else "")
    return {"family": family, "role": role, "company": company, "header": re.sub(r"\s+", " ", header),
            "location_line": cv.location_line(row, cvcfg, sc), "paragraphs": paras,
            "greeting": f"Dear {company} hiring team,", "asked": asked_for(text), "me": me(ccfg)}


def to_html(letter: dict, when: date | None = None) -> str:
    when = when or date.today()
    esc = lambda s: htmllib.escape(s, quote=False)
    body = "\n".join(f"<p>{p}</p>" for p in letter["paragraphs"])
    who = letter.get("me") or {}
    name, email, phone = who.get("name", ""), who.get("email", ""), who.get("phone", "")
    spans = [f"<span>{esc(letter['location_line'])}</span>"]
    if email:
        spans.append(f'<span><a class="cvlink" href="mailto:{esc(email)}">{esc(email)}</a></span>')
    if phone:
        spans.append(f"<span>{esc(phone)}</span>")
    for link in who.get("links") or []:    # written without https://, e.g. linkedin.com/in/your-name
        spans.append(f'<span><a class="cvlink" href="https://{esc(link)}">{esc(link)}</a></span>')
    contact = '<span class="sep">|</span>\n    '.join(spans)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" /><title>{esc(name)} Cover Letter</title><style>{STYLE}</style></head>
<body>
<div class="head">
  <h1>{esc(name.upper())}</h1>
  <div class="role">{esc(letter['header'])}</div>
  <div class="contact">
    {contact}
  </div>
</div>
<div class="date">{when.day} {when:%B %Y}</div>
<p>{esc(letter['greeting'])}</p>
{body}
<p class="sig">{esc(name)}<br />{esc(", ".join(x for x in (email, phone) if x))}</p>
</body></html>"""


def to_text(letter: dict, row: dict, ccfg: dict) -> str:
    plain = lambda s: re.sub(r"<[^>]+>", "", s)
    who = letter.get("me") or me(ccfg)
    parts = [letter["greeting"], "", *[plain(p) + "\n" for p in letter["paragraphs"]], who.get("name", ""),
             ", ".join(x for x in (who.get("email"), who.get("phone")) if x), "", "",
             "FORM ANSWERS (copy the value after the label)", ""]
    width = max(len(k) for k in ccfg["answers"]) + 3
    for k, v in ccfg["answers"].items():
        parts.append(f"{k.ljust(width)}{v}")
    parts.append(f"{'Expected pay'.ljust(width)}{expected_pay(row, ccfg)}")
    parts += ["", "SHORT ABOUT ME (for 'tell us about yourself' boxes)", "", ccfg.get("about_me", "").strip()]
    return "\n".join(parts)


def _slug(text: str, n: int) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", text)).strip("_")[:n].strip("_")


def assign(rows: list[dict], store, sc: dict, log=print, max_builds: int = 60) -> dict:
    """Fill row["Cover letter"] and row["_cl_link"] for Apply Queue rows, building missing letters."""
    from jobhunter.excel import queue_ok
    ccfg, cvcfg = load_config(), cv.load_config()
    out_dir = ROOT / ccfg.get("output_dir", "output/cover_letters")
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = Path(ccfg.get("output_dir", "output/cover_letters")).name
    todo, stats = [], {"ready": 0, "built": 0}
    for row in rows:
        key = row.get("Key")
        prior = store.cover_letter(key)
        if not queue_ok(row):
            if prior and (out_dir / prior["file"]).exists():   # keep the link on jobs you applied to
                row["Cover letter"] = "Cover letter" + (" (asked for)" if prior["asked"] else "")
                row["_cl_link"] = f"{rel}/{prior['file']}"
            continue
        text = store.text(key)
        letter = compose(row, text, sc, ccfg, cvcfg)
        html = to_html(letter)
        bad = cv.visible_banned(html)
        if bad:
            log(f"cover letter for '{row.get('Title')}' would contain banned marks {bad[:2]}, not built")
            continue
        digest = hashlib.sha1((html + expected_pay(row, ccfg)).encode("utf-8")).hexdigest()[:12]
        prefix = _slug(str(me(ccfg).get("name") or ""), 30)
        name = f"{prefix + '_' if prefix else ''}Cover_Letter_{_slug(letter['company'], 24)}_{_slug(letter['role'], 40)}"
        label = "Cover letter" + (" (asked for)" if letter["asked"] else "")
        if prior and prior["hash"] == digest and (out_dir / prior["file"]).exists():
            row["Cover letter"], row["_cl_link"] = label, f"{rel}/{prior['file']}"
            stats["ready"] += 1
            continue
        if len(todo) >= max_builds:
            continue
        (out_dir / f"{name}.txt").write_text(to_text(letter, row, ccfg), encoding="utf-8")
        todo.append((html, out_dir / f"{name}.pdf", key, digest, letter["asked"], row, label))
    if todo:
        cv.render([(h, p) for h, p, *_ in todo], log)
        for html, path, key, digest, asked, row, label in todo:
            if path.exists():
                store.save_cover_letter(key, path.name, digest, asked)
                row["Cover letter"], row["_cl_link"] = label, f"{rel}/{path.name}"
                stats["built"] += 1
        log(f"built {stats['built']} cover letter(s) in {out_dir}")
    return stats
