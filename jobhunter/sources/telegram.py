"""Public Telegram channels, read through Telegram's web preview (https://t.me/s/<channel>).

No Telegram account or API key needed. Only public *channels* work (not private groups), and
only text posts (some channels post formats the preview can't show).

Config:
  channels:
    - { name: laborx, format: laborx, kind: freelance, pages: 3 }
  format → how a post is turned into jobs:
    laborx          "NEW PROJECT ON LABORX" posts (budget, skills); other posts ignored
    cryptojobslist  "💼 Title / 🏛️ at Company / 🌍 Location / 💰 Salary / Apply → link"
    dejob           "#Recruitment / 🏡 Company / 🛵 #FullTime #Remote / 📚 #Role / 💰 Compensation"
    digest          several "• Company is hiring <Title link>" lines per post
    generic         first meaningful line = title, first external link = apply link
"""
import re
import time

from bs4 import BeautifulSoup

from jobhunter.models import Job
from jobhunter.util import detect_work_mode, http_client, to_date

EMOJI_ONLY = re.compile(r"^[\W_\d️⃣]*$")


def _lines(node):
    return [l.strip() for l in node.get_text("\n", strip=True).split("\n") if l.strip()]


def _external_links(node):
    return [a["href"] for a in node.select("a[href]")
            if a["href"].startswith("http") and "t.me/" not in a["href"]]


def _after(lines, marker):
    """Text of the first line that follows a line containing marker."""
    for i, l in enumerate(lines):
        if marker in l and i + 1 < len(lines):
            return lines[i + 1]
    return ""


def _value(lines, prefix):
    for l in lines:
        if l.lower().startswith(prefix.lower()):
            return l.split(":", 1)[-1].strip()
    return ""


def parse_laborx(text_node, lines, base):
    if not any("NEW PROJECT" in l for l in lines[:3]):
        return []  # gigs of the day, success stories, trending skills… are not paid work for you
    meaningful = [l for l in lines if not EMOJI_ONLY.match(l) and "NEW PROJECT" not in l]
    title = meaningful[0] if meaningful else ""
    budget = _value(lines, "Budget")
    skills = _after(lines, "Budget")
    links = [u for u in _external_links(text_node) if "laborx.com/jobs/" in u]
    return [dict(base, title=title, company="LaborX client", salary=f"{budget} (budget)" if budget else "",
                 url=links[0] if links else base["url"], description=" ".join(lines), extra_tags=skills)]


def parse_cryptojobslist(text_node, lines, base):
    title = next((lines[i + 1] for i, l in enumerate(lines) if l == "💼" and i + 1 < len(lines)), "")
    if not title:
        return []
    company = next((lines[i + 1] for i, l in enumerate(lines) if l == "🏛️" and i + 1 < len(lines)), "")
    location = next((lines[i + 1] for i, l in enumerate(lines) if l == "🌍" and i + 1 < len(lines)), "")
    salary = next((lines[i + 1] for i, l in enumerate(lines) if l == "💰" and i + 1 < len(lines)), "")
    links = _external_links(text_node)
    return [dict(base, title=title, company=re.sub(r"^at\s+", "", company), location=location, salary=salary,
                 url=links[0] if links else base["url"], description=" ".join(lines))]


def parse_dejob(text_node, lines, base):
    if not any("Recruitment" in l for l in lines[:3]):
        return []
    company = _after(lines, "🏡")
    tags_block = lines[lines.index("🛵") + 1: lines.index("📚")] if "🛵" in lines and "📚" in lines else []
    role_block = lines[lines.index("📚") + 1: lines.index("💰")] if "📚" in lines and "💰" in lines else []
    roles = " / ".join(r.lstrip("#").replace("·", " ") for r in role_block if r.startswith("#"))
    location = ", ".join(t.lstrip("#") for t in tags_block if t.lstrip("#") not in ("FullTime", "PartTime"))
    links = [u for u in _external_links(text_node) if "dejob.ai/jobDetail" in u] or _external_links(text_node)[1:2]
    part_time = any(t in ("#PartTime", "#Freelance", "#Contract") for t in tags_block)
    return [dict(base, title=roles or "Web3 role", company=company, location=location,
                 salary=_value(lines, "Compensation"), url=links[0] if links else base["url"],
                 description=" ".join(lines), kind="freelance" if part_time else base["kind"])]


def parse_digest(text_node, lines, base):
    jobs = []
    for a in text_node.select("a[href]"):
        before = a.previous_sibling
        m = re.search(r"•\s*(.+?)\s+is hiring", str(before or ""))
        if m:
            jobs.append(dict(base, title=a.get_text(strip=True), company=m.group(1).strip(),
                             url=a["href"].split("?")[0], description=f"{m.group(1)} is hiring {a.get_text(strip=True)} web3"))
    return jobs


def parse_generic(text_node, lines, base):
    meaningful = [l for l in lines if not EMOJI_ONLY.match(l) and not l.startswith("#")]
    if not meaningful:
        return []
    links = _external_links(text_node)
    return [dict(base, title=meaningful[0][:120], url=links[0] if links else base["url"], description=" ".join(lines))]


PARSERS = {"laborx": parse_laborx, "cryptojobslist": parse_cryptojobslist, "dejob": parse_dejob,
           "digest": parse_digest, "generic": parse_generic}


def fetch(cfg, profile, log):
    jobs = []
    with http_client(log=log) as client:
        for ch in cfg["channels"]:
            parser = PARSERS[ch.get("format", "generic")]
            before, posts, unreadable = None, 0, 0
            for _ in range(ch.get("pages", 2)):  # each page = ~20 most recent posts, then older
                try:
                    resp = client.get(f"https://t.me/s/{ch['name']}", params={"before": before} if before else None)
                except Exception as e:
                    log(f"WARNING {ch['name']} page failed after retries ({type(e).__name__}), skipped")
                    break
                messages = BeautifulSoup(resp.text, "lxml").select("div.tgme_widget_message")
                if not messages:
                    break
                for m in messages:
                    posts += 1
                    text_node = m.select_one(".tgme_widget_message_text")
                    if text_node is None:
                        unreadable += 1
                        continue
                    date_node = m.select_one("time[datetime]")
                    base = dict(url=f"https://t.me/{m.get('data-post', ch['name'])}", company="", location="",
                                salary="", kind=ch.get("kind", "job"))
                    for item in parser(text_node, _lines(text_node), base):
                        tags = item.pop("extra_tags", "")
                        jobs.append(Job(
                            source=f"Telegram: {ch['name']}", title=item["title"], url=item["url"],
                            company=item["company"], location=item["location"],
                            work_mode=detect_work_mode(item["location"], item["title"], item["description"][:300]),
                            posted=to_date(date_node["datetime"] if date_node else None), salary=item["salary"],
                            description=f"{item['description']} {tags}"[:6000],
                            web3_native=ch.get("web3_native", True), kind=item["kind"]))
                before = messages[0].get("data-post", "").rsplit("/", 1)[-1] or None
                time.sleep(1)
            log(f"{ch['name']}: {posts} posts read → {sum(1 for j in jobs if j.source.endswith(ch['name']))} jobs"
                + (f" ({unreadable} posts not readable in web preview)" if unreadable else ""))
            if posts and unreadable == posts:
                log(f"WARNING: {ch['name']} posts can't be read via the web preview — check it in the Telegram app")
    return jobs
