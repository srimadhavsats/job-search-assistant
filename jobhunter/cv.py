"""Which CV to send for each job, and job-specific copies built automatically (added 2026-09-25).

config/cvs.yaml maps each job to a template (TM and AML, Research, General, One page) with the
PLAYBOOK section 5 rules. For good jobs you can apply to, a copy is built from the template's HTML
with two lines changed and nothing else:

  headline  "<the job's own title> | <template tagline>"   (seniority words, places, contract
            terms and banned punctuation removed from the title)
  location  matches the job: remote, relocation to that Indian city, or visa sponsorship abroad

It is rendered to PDF with installed Google Chrome (channel="chrome", prefer_css_page_size), the
same way the hand-made CVs are, into output/cvs/. The workbook's CV column links to it, so opening
a job and the right CV is one click each. PDFs are rebuilt only when the template or the two lines
change, and ones no longer linked from the workbook are deleted after keep_days.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from jobhunter.scoring import _hits

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"[;:—–→·]")          # ; : em dash, en dash, arrow, middot
LOCK_WORDS = ("can't apply from India", "Needs ", "Title names", "Title is for", "Text requires", "Abroad on-site",
              "Unpaid", "Students and recent graduates", "Apply page", "Closed", "SCAM", "Internship abroad",
              "Looks like the job you already applied")
_SENIORITY = re.compile(r"\b(?:senior|sr\.?|snr|lead|principal|staff|junior|jr\.?|intern(?:ship)?|trainee|"
                        r"head of|vp|director|i{1,3}|iv|l[1-3]|level [1-3]|entry[- ]level|mid[- ]level)\b", re.I)
_NOISE = re.compile(r"\b(?:remote|hybrid|on-?site|full[- ]time|part[- ]time|contract(?:or)?|temporary|permanent|"
                    r"\d+\s*months?|\d+months|m/f/d|f/m/d|w/m/d|all genders|urgent(?:ly)?|hiring|immediate joiner|"
                    r"location|(?:us|uk|eu|emea|apac|latam|est|pst|cet|ist|asia)?\s*time\s*zones?|us|usa|uk|eu)\b", re.I)
_SMALL = {"and", "of", "for", "the", "in", "on", "to", "with", "a", "an"}


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "cvs.yaml").read_text(encoding="utf-8"))


def pick(row: dict, cfg: dict) -> str:
    title = str(row.get("Title") or "").lower()
    company = str(row.get("Company") or "").lower()
    source = str(row.get("Source") or "")
    for rule in cfg["rules"]:
        if rule.get("sources") and source not in rule["sources"]:
            continue
        if rule.get("companies") and not _hits(company, rule["companies"]):
            continue
        if rule.get("title_words") and not _hits(title, rule["title_words"]):
            continue
        return rule["template"]
    return "general"


def clean_title(title: str, sc: dict) -> str:
    """Job title as a CV headline: no seniority, places, contract terms, other scripts or banned marks."""
    t = re.sub(r"\s*[–—]\s*", " - ", str(title or ""))        # en and em dashes separate parts
    t = re.sub(r"[^\x20-\x7E]", " ", t)                                  # drops 区块链测试工程师, emoji…
    places = sc.get("title_region_words", []) + sc.get("india_or_global_locations", []) + ["apac", "emea", "latam"]

    def keep(part: str) -> bool:
        """A part stays if something other than places and work terms is left in it."""
        p = _NOISE.sub(" ", part.lower())
        for place in places:
            p = re.sub(rf"(?<![a-z]){re.escape(str(place).lower())}(?![a-z])", " ", p)
        return bool(re.search(r"[a-z]{2,}", p))

    # brackets: keep a specialism ("Enhanced Due Diligence"), drop "(Remote - US)", "(12 months)"
    t = re.sub(r"[\(\[]([^\)\]]*)[\)\]]", lambda m: f", {m.group(1)}" if keep(m.group(1))
               and not re.search(r"\d", m.group(1)) else " ", t)
    parts = [p for p in re.split(r"\s+[-|/]\s+|\s*[:;,]\s*|\s+-\s*$", t) if keep(p)]
    t = ", ".join(_NOISE.sub(" ", p) for p in parts)
    t = _SENIORITY.sub(" ", t)
    for place in sorted(places, key=len, reverse=True):        # "… Specialist Japan Japan Location Japan"
        t = re.sub(rf"(?<![A-Za-z]){re.escape(str(place))}(?![A-Za-z])", " ", t, flags=re.I)
    t = t.replace("&", " and ").replace("/", " and ")
    t = BANNED.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+,", ",", re.sub(r"(?:,\s*){2,}", ", ", t)).strip(" ,.-")
    t = re.sub(r"^(?:and|of|for|the)\s+|\s+(?:and|of|for|the)$", "", t, flags=re.I).strip(" ,.-")
    # "Customer support agent" -> "Customer Support Agent". Acronyms (AML, CSIRT, OEX) stay as they are.
    t = " ".join(w if (i and w.lower() in _SMALL) or sum(c.isupper() for c in w) >= 2 else w[:1].upper() + w[1:]
                 for i, w in enumerate(t.split(" ")))
    return t[:70].rsplit(" ", 1)[0] if len(t) > 70 else t


def role_line(title: str, template: dict, sc: dict) -> str | None:
    head = clean_title(title, sc)
    if len(head) < 4:
        return None
    parts = [head] + [t for t in template.get("tagline", []) if t.lower() not in head.lower()]
    return " | ".join(parts[:3])


def location_line(row: dict, cfg: dict, sc: dict) -> str:
    lines = cfg["location_lines"]
    loc = str(row.get("Location") or "")
    low = loc.lower()
    remote = str(row.get("Work mode") or "") == "Remote" or "remote" in low or "anywhere" in low or "worldwide" in low
    if remote:
        return lines["remote"]
    home = str(cfg.get("home_city") or "").lower()
    if home and home in low:
        return lines["home"]
    city = next((c for c in ["Bengaluru", "Bangalore", "Mumbai", "Gurugram", "Gurgaon", "Noida", "New Delhi", "Delhi",
                             "Hyderabad", "Pune", "Chennai", "Kolkata", "Ahmedabad", "Jaipur", "Indore", "Chandigarh",
                             "Kochi", "Gandhinagar", "Kanpur", "Nashik", "Mohali"] if c.lower() in low), None)
    if city:
        return lines["india_city"].format(city={"Bangalore": "Bengaluru", "Gurgaon": "Gurugram"}.get(city, city))
    if "india" in low:
        return lines["india"]
    if _hits(low, sc.get("visa_typical_locations", [])):
        return lines["gulf"]
    if loc:
        return lines["abroad"]
    return lines["remote"]


def _edit_html(html: str, role: str, location: str, title: str = "CV") -> str:
    esc = lambda s: htmllib.escape(s, quote=False)
    html = re.sub(r'(<div class="role">)(.*?)(</div>)', lambda m: m.group(1) + esc(role) + m.group(3), html, count=1, flags=re.S)
    html = re.sub(r'(<div class="contact">\s*<span>)(.*?)(</span>)', lambda m: m.group(1) + esc(location) + m.group(3),
                  html, count=1, flags=re.S)
    return re.sub(r"<title>.*?</title>", f"<title>{esc(title)}</title>", html, count=1, flags=re.S)


def visible_banned(html: str) -> list[str]:
    """Banned marks in the text a recruiter sees (links and e-mail addresses excluded)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["style", "script", "title"]):
        tag.decompose()
    text = re.sub(r"https?://\S+|\S+@\S+", "", soup.get_text(" ", strip=True))
    return [text[max(0, m.start() - 25):m.end() + 15] for m in BANNED.finditer(text)]


def _slug(text: str, n: int) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", text)).strip("_")[:n].strip("_")


def render(items: list[tuple[str, Path]], log=print) -> int:
    """Render (html, pdf_path) pairs with installed Chrome. Returns how many were written."""
    if not items:
        return 0
    from playwright.sync_api import sync_playwright
    done = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            for html, out in items:
                try:
                    page.set_content(html, wait_until="load")
                    tmp = out.with_suffix(".tmp.pdf")
                    page.pdf(path=str(tmp), prefer_css_page_size=True, print_background=True)
                    tmp.replace(out)
                    done += 1
                except Exception as e:
                    log(f"CV render failed for {out.name}: {e!r}"[:200])
        finally:
            browser.close()
    return done


def ensure_base_pdfs(cfg: dict, log=print) -> None:
    """Re-render a template's own PDF when its HTML was edited after the PDF was made."""
    todo = []
    for tid, t in cfg["templates"].items():
        src, pdf = ROOT / t["html"], ROOT / t["pdf"]
        if pdf in [p for _, p in todo]:      # several templates may share one file
            continue
        if src.exists() and (not pdf.exists() or src.stat().st_mtime > pdf.stat().st_mtime + 60):
            todo.append((src.read_text(encoding="utf-8"), pdf))
    if todo:
        n = render(todo, log)
        log(f"re-rendered {n} template PDF(s) whose HTML changed: {', '.join(p.name for _, p in todo)}")


def _copy_prebuilt(cfg: dict, out_dir: Path) -> None:
    for t in cfg["templates"].values():
        src = ROOT / t["pdf"]
        dst = out_dir / src.name
        if src.exists() and (not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime):
            shutil.copy2(src, dst)


def applicable(row: dict) -> bool:
    flags = f"{row.get('Flags') or ''} {row.get('Link check') or ''}"
    return not any(w in flags for w in LOCK_WORDS) and "not seen since" not in flags


def assign(rows: list[dict], store, sc: dict, log=print, build: bool = True, max_builds: int = 60) -> dict:
    """Fill row["CV"] (label) and row["_cv_link"] (path relative to the workbook) for every row.

    rows: every job row that will be written (All Jobs and Freelance). Custom CVs are built for good,
    applicable, New rows. Returns counts for the log."""
    cfg = load_config()
    out_dir = ROOT / cfg.get("output_dir", "output/cvs")
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = Path(cfg.get("output_dir", "output/cvs")).name   # links are relative to output/Jobs.xlsx
    ensure_base_pdfs(cfg, log)
    _copy_prebuilt(cfg, out_dir)
    known = store.all_custom_cvs()
    owners = {v["file"]: (k, v["hash"]) for k, v in known.items()}
    todo, stats = [], {"custom": 0, "built": 0, "prebuilt": 0}
    for row in rows:
        key = row.get("Key")
        tid = pick(row, cfg)
        template = cfg["templates"][tid]
        label, link = template["label"], f"{rel}/{Path(template['pdf']).name}"
        freelance = row.get("_kind") == "freelance"
        wants_custom = (template.get("custom") and not freelance and build
                        and (row.get("Score") or 0) >= cfg.get("custom_min_score", 55)
                        and applicable(row) and str(row.get("Status") or "New") == "New")
        prior = known.get(key)
        if wants_custom:
            role = role_line(str(row.get("Title") or ""), template, sc)
            src = ROOT / template["html"]
            if role and src.exists():
                loc = location_line(row, cfg, sc)
                html = _edit_html(src.read_text(encoding="utf-8"), role, loc, f"{cfg.get('name') or ''} CV".strip())
                digest = hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
                if prior and prior["hash"] == digest and (out_dir / prior["file"]).exists():
                    label, link = f"{template['label']} (custom)", f"{rel}/{prior['file']}"
                    stats["custom"] += 1
                elif len(todo) < max_builds:
                    bad = visible_banned(html)
                    if bad:
                        log(f"custom CV for '{row.get('Title')}' would contain banned marks {bad[:2]}, sent the standard one")
                    else:
                        prefix = _slug(str(cfg.get("name") or ""), 30)
                        base = f"{prefix + '_' if prefix else ''}CV_{_slug(str(row.get('Company') or ''), 24)}_{_slug(clean_title(str(row.get('Title') or ''), sc), 40)}"
                        name, n = f"{base}.pdf", 2
                        while name in owners and owners[name][0] != key and owners[name][1] != digest:
                            name, n = f"{base}_{n}.pdf", n + 1
                        owners[name] = (key, digest)
                        todo.append((html, out_dir / name, key, tid, digest, row))
                        continue
        elif prior and (out_dir / prior["file"]).exists():
            # already applied or skipped: keep pointing at the CV that was sent
            label, link = f"{cfg['templates'].get(prior['template'], template)['label']} (custom)", f"{rel}/{prior['file']}"
            stats["custom"] += 1
            row["CV"], row["_cv_link"] = label, link
            continue
        row["CV"], row["_cv_link"] = label, link
        stats["prebuilt"] += 1 if "(custom)" not in label else 0

    if todo:
        written = render([(h, p) for h, p, *_ in todo], log)
        for html, path, key, tid, digest, row in todo:
            if path.exists():
                store.save_custom_cv(key, tid, path.name, digest)
                row["CV"], row["_cv_link"] = f"{cfg['templates'][tid]['label']} (custom)", f"{rel}/{path.name}"
                stats["built"] += 1
            else:
                t = cfg["templates"][tid]
                row["CV"], row["_cv_link"] = t["label"], f"{rel}/{Path(t['pdf']).name}"
        log(f"built {written} job-specific CV(s) in {out_dir}")
    _cleanup(rows, store, out_dir, cfg)
    return stats


def _cleanup(rows, store, out_dir: Path, cfg: dict):
    """Delete custom CVs whose job left the workbook more than keep_days ago."""
    live = {r.get("Key") for r in rows}
    linked = {str(r.get("_cv_link") or "").split("/")[-1] for r in rows}
    cutoff = datetime.now() - timedelta(days=cfg.get("keep_days", 30))
    for key, info in store.all_custom_cvs().items():
        if key in live:
            continue
        try:
            built = datetime.fromisoformat(info["built_at"])
        except (TypeError, ValueError):
            built = datetime.now()
        if built < cutoff:
            if info["file"] not in linked:
                (out_dir / info["file"]).unlink(missing_ok=True)
            store.forget_custom_cv(key)


def referral_message(row: dict, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    tid = pick(row, cfg)
    text = cfg["referral_messages"].get(tid) or cfg["referral_messages"]["general"]
    link = re.sub(r"^https?://(www\.)?", "", str(row.get("Apply link") or ""))
    role = re.sub(r"\s+", " ", BANNED.sub(" ", re.sub(r"[^\x20-\x7E]", " ", str(row.get("Title") or "")))).strip(" ,")
    company = BANNED.sub(" ", str(row.get("Company") or "the company")).strip()
    return text.format(role=role, company=company, link=link)
