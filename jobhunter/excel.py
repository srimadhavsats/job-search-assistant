"""Excel output (output/Jobs.xlsx).

Tabs, left to right:
  Apply Queue    New jobs worth applying to now, freshest first, each with its CV, a referrer search
                 and a ready referral message (added 2026-09-25)
  Remote Jobs    remote jobs you can do from India (added 2026-09-25)
  Freelance      bounties, gigs, part-time work
  All Jobs       everything ever found, your application tracker
  one per day    jobs first seen that day
  Earn Platforms, Health (per-source status, added 2026-09-25), Run Log

Your Status and Notes are kept, whichever tab you edit them in. Each row carries hidden "Saved status"
and "Saved notes" columns with what was written last time, so an edit is recognised as the cell that
differs from its saved copy, in any tab. Before 2026-09-25 only "non-New" statuses were merged, and an
Applied set in All Jobs could be overwritten by a "New" on the same day's tab.

If the workbook is open, results go to a side file (Jobs_<date_time>.xlsx). Side files are
folded back into the main workbook on the next save once it is closed: new rows added, edits kept.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

# Status is the first column and Priority reads "✓ Applied" once you have acted (2026-09-26: Status sat
# far to the right and Priority still said "1 - Apply now" on jobs already applied to).
COLS = ["Status", "Priority", "Score", "Title", "Company", "Location", "Work mode", "Apply link", "CV", "Cover letter",
        "Link check", "Notes", "Posted", "Salary", "Experience", "Deadline", "Why it matched", "Flags", "Source",
        "Status date", "Also on", "First seen", "Found at", "Last seen", "Key", "Saved status", "Saved notes"]
QUEUE_COLS = ["Status", "Priority", "Score", "Title", "Company", "Location", "Work mode", "Apply link", "CV", "Cover letter",
              "Find referrer", "Referral message", "Link check", "Notes", "Posted", "Salary", "Experience", "Deadline",
              "Why it matched", "Flags", "Source", "Status date", "First seen", "Found at", "Key", "Saved status", "Saved notes"]
WIDTHS = {"Priority": 13, "Score": 7, "Source": 18, "Title": 42, "Company": 20, "Location": 22, "Work mode": 10, "Posted": 11,
          "Salary": 16, "Experience": 16, "Deadline": 11, "Why it matched": 50, "Flags": 24, "Apply link": 9, "CV": 20,
          "Link check": 13, "Status": 11, "Notes": 28, "Also on": 14, "First seen": 11, "Found at": 16, "Last seen": 11,
          "Key": 4, "Saved status": 4, "Saved notes": 4, "Find referrer": 12, "Referral message": 40,
          "Status date": 11, "Days since": 8, "Follow-up message": 44, "Cover letter": 20}
FOLLOW_COLS = ["Status", "Title", "Company", "Status date", "Days since", "Apply link", "Find referrer",
               "Follow-up message", "Notes", "Location", "CV", "Source", "Key", "Saved status", "Saved notes"]
FOLLOW_UP = ("Hi NAME, following up on my application for {role} at {company}. Still very interested. "
             "In case it helps, here is a short sample relevant to your team LINK. Thank you.")
HIDDEN = ("Key", "Saved status", "Saved notes")
# "Not relevant" (2026-09-26): the job is wrong for you. Similar titles are pushed down in future runs.
# "Skip" means relevant but you are not applying.
STATUSES = ["New", "Applied", "Interview", "Offer", "Rejected", "Skip", "Not relevant"]
STATUS_RANK = {"Offer": 6, "Rejected": 5, "Interview": 4, "Applied": 3, "Not relevant": 2, "Skip": 2, "New": 1}
STATUS_LABEL = {"Applied": "✓ Applied", "Interview": "★ Interview", "Offer": "★ Offer", "Rejected": "✗ Rejected",
                "Skip": "– Skipped", "Not relevant": "✗ Not relevant"}
STATUS_FILLS = {"Applied": "E2EFDA", "Interview": "FFE699", "Offer": "A9D08E", "Rejected": "F8CBAD",
                "Skip": "EDEDED", "Not relevant": "EDEDED"}
TODAY_SHEET = "Today"
ALL_SHEET, LOG_SHEET, FREELANCE_SHEET, EARN_SHEET = "All Jobs", "Run Log", "Freelance", "Earn Platforms"
QUEUE_SHEET, REMOTE_SHEET, HEALTH_SHEET, FOLLOW_SHEET = "Apply Queue", "Remote Jobs", "Health", "Follow Ups"
VIEW_SHEETS = (QUEUE_SHEET, FOLLOW_SHEET, REMOTE_SHEET)
EARN_COLS = ["Priority", "Fit", "Platform", "Type", "What you would do", "Why it fits you", "Pay & speed",
             "Checked", "Link", "Status", "Notes"]
EARN_WIDTHS = [13, 6, 24, 16, 42, 46, 30, 12, 34, 12, 28]
HEADER_FILL = PatternFill("solid", fgColor="1A1F2B")
LOG_COLS = ["Run at", "Source", "Jobs fetched", "Kept (score ≥ min)", "New today", "Result / error"]
HEALTH_COLS = ["Source", "Checked every", "Last OK", "Last check", "Result", "Jobs last time", "Usual", "Failures in a row", "Next check"]
LINK_FONT = Font(color="0563C1", underline="single")
LOCK_WORDS = ("can't apply from India", "Needs ", "Title names", "Title is for", "Text requires", "Abroad on-site",
              "Unpaid", "Students and recent graduates", "Apply page", "Closed (apply page", "Country-locked",
              "Region-limited", "⛔", "SCAM", "Internship abroad", "Looks like the job you already applied")
RUN_LOG_DAYS = 14


@dataclass
class SaveResult:
    path: Path
    rows: dict = field(default_factory=dict)      # key -> row written to All Jobs / Freelance
    side_files_merged: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)      # what the Today tab shows (also used by Telegram)
    actions_saved: list = field(default_factory=list)   # Telegram actions now stored in the main workbook

    def __fspath__(self):
        return str(self.path)


def _is_day(name: str) -> bool:
    return name[:2] == "20" and len(name) == 10


def _read(ws) -> dict[str, dict]:
    if ws is None or ws.max_row < 2:
        return {}
    header = [c.value for c in ws[1]]
    rows = {}
    for cells in ws.iter_rows(min_row=2):
        row = {h: c.value for h, c in zip(header, cells) if h}
        for h, c in zip(header, cells):
            if h in ("Apply link", "CV", "Find referrer", "Cover letter") and c.hyperlink is not None:
                row[{"Apply link": "Apply link", "CV": "_cv_link", "Find referrer": "_referrer",
                     "Cover letter": "_cl_link"}[h]] = c.hyperlink.target
        if "Saved status" in header:
            row["_has_saved"] = True
        if row.get("Key"):
            rows[row["Key"]] = row
    return rows


def _edited(row: dict) -> tuple[bool, bool]:
    """(status edited, notes edited) compared with what was written last time."""
    status, notes = str(row.get("Status") or "New"), str(row.get("Notes") or "")
    if row.get("_has_saved"):
        return status != str(row.get("Saved status") or "New"), notes != str(row.get("Saved notes") or "")
    return status != "New", bool(notes)          # workbook written before 2026-09-25


def resolve_user_fields(master: dict, copies: list[dict]) -> tuple[str, str]:
    """Status and Notes for one job, given its master row (All Jobs or Freelance) and its copies in
    other tabs and side files, in priority order. An edit anywhere wins over an untouched cell."""
    rows = [master] + copies
    edits = [r for r in rows if _edited(r)[0]]
    status = (max(edits, key=lambda r: STATUS_RANK.get(str(r.get("Status")), 0))["Status"] if edits
              else master.get("Status") or "New")
    notes_edit = next((r for r in rows if _edited(r)[1]), None)
    notes = notes_edit.get("Notes") if notes_edit else master.get("Notes")
    return status or "New", notes or ""


def _job_row(job, first_seen: str, today: date, found_at: str = "") -> dict:
    return {"Deadline": job.deadline.isoformat() if job.deadline else "",
            "Priority": job.priority, "Score": job.score, "Source": job.source, "Title": job.title, "Company": job.company,
            "Location": job.location, "Work mode": job.work_mode,
            "Posted": job.posted.isoformat() if job.posted else "", "Salary": job.salary,
            "Experience": job.experience, "Why it matched": job.why, "Flags": job.flags, "Apply link": job.url,
            "Status": "New", "Notes": "", "Also on": ", ".join(job.also_on), "First seen": first_seen,
            "Found at": found_at, "Last seen": today.isoformat(), "Key": job.key, "_kind": job.kind}


def locked(row: dict) -> bool:
    flags = f"{row.get('Flags') or ''} {row.get('Link check') or ''}"
    return any(w in flags for w in LOCK_WORDS) or "not seen since" in flags or str(row.get("Link check") or "").startswith("Closed")


def is_remote(row: dict) -> bool:
    loc = str(row.get("Location") or "").lower()
    return (str(row.get("Work mode") or "") == "Remote" or any(w in loc for w in ("remote", "anywhere", "worldwide",
                                                                                   "work from home", "wfh")))


def remote_ok(row: dict, min_score: int = 35) -> bool:
    return is_remote(row) and not locked(row) and (row.get("Score") or 0) >= min_score


def queue_ok(row: dict, min_score: int = 55) -> bool:
    """Jobs only: gigs have their own Freelance tab (Freelancer.com gigs flooded the queue on 2026-09-25)."""
    why, flags, score = str(row.get("Why it matched") or ""), str(row.get("Flags") or ""), row.get("Score") or 0
    # PLAYBOOK section 5: skip Senior, Lead and Manager titles unless they still score 70+, and posts
    # a year or more old (evergreen listings rarely hire). They stay visible in All Jobs and Remote Jobs.
    if score < 70 and ("senior title" in why or "manager title" in why):
        return False
    if "Old post (" in flags:
        return False
    return (row.get("_kind") != "freelance" and str(row.get("Status") or "New") == "New" and not locked(row)
            and score >= min_score)


def _company_core(name) -> str:
    """"JPMorganChase", "JPMorgan Chase Bank" and "JP Morgan Services India Pvt Ltd" all become "jpmorgan"."""
    n = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    n = re.sub(r"\b(?:inc|ltd|limited|llc|llp|pvt|private|plc|corp|corporation|co|company|bank|group|holdings?|"
               r"technologies|technology|tech|labs?|services|solutions|global|india|international|chase|the|na)\b", " ", n)
    n = re.sub(r"\s+", "", n)
    changed = True
    while changed:                         # "jpmorganchase" (written as one word) loses "chase" too
        changed = False
        for suffix in ("chase", "bank", "inc", "ltd", "llc", "limited", "services", "india", "labs", "group"):
            if n.endswith(suffix) and len(n) > len(suffix) + 2:
                n, changed = n[: -len(suffix)], True
    return n[:12]


def _title_words(title) -> set:
    stop = {"and", "of", "the", "for", "a", "an", "in", "senior", "junior", "sr", "jr", "i", "ii", "iii", "remote"}
    return {w for w in re.findall(r"[a-z0-9]+", str(title or "").lower()) if w not in stop}


def mark_applied_duplicates(rows: list[dict]) -> int:
    """A New row that looks like a job you already applied to at the same company (same job reposted on
    another site, e.g. JP Morgan Quality Analyst on Apna, Indeed and Naukri) is flagged and kept out of
    the queue and alerts. Other New rows at that company get a note, handy for reusing a referral."""
    done = {}
    for r in rows:
        if str(r.get("Status") or "New") not in ("New", "Skip") and r.get("Company"):
            done.setdefault(_company_core(r["Company"]), []).append(r)
    n = 0
    for r in rows:
        if str(r.get("Status") or "New") != "New":
            continue
        others = done.get(_company_core(r.get("Company")))
        if not others:
            continue
        mine = _title_words(r.get("Title"))
        flags = str(r.get("Flags") or "")
        for o in others:
            theirs = _title_words(o.get("Title"))
            overlap = len(mine & theirs) / max(1, min(len(mine), len(theirs)))
            if mine and theirs and overlap >= 0.99 and "applied to" not in flags:
                # identical title: hidden from the queue. One title inside the other: a warning only,
                # because hiding a real second opening would be worse than a second look.
                label = "Looks like the job you already applied to" if mine == theirs else "Maybe the same job you applied to"
                r["Flags"] = "; ".join(filter(None, [f"{label} ({o.get('Title')}, {o.get('Status')})", flags]))
                n += 1
                break
        else:
            if "at this company" not in flags:
                r["Flags"] = "; ".join(filter(None, [f"You already applied at this company ({len(others)})", flags]))
    return n


def follow_ups(rows: list[dict], today: date, first: int = 5, last: int = 21) -> list[dict]:
    """Applied 5 to 21 days ago and still only "Applied": time for one polite follow-up (PLAYBOOK section 8).
    Rows applied before 2026-09-25 have no Status date, so their First seen date stands in."""
    out = []
    for r in rows:
        if str(r.get("Status") or "") != "Applied" or "followed up" in str(r.get("Notes") or "").lower():
            continue
        when = str(r.get("Status date") or r.get("First seen") or "")[:10]
        try:
            days = (today - date.fromisoformat(when)).days
        except ValueError:
            continue
        if first <= days <= last:
            role = re.sub(r"\s+", " ", re.sub(r"[;:—–→·]", " ", str(r.get("Title") or ""))).strip()
            r["Days since"] = days
            r["Follow-up message"] = FOLLOW_UP.format(role=role, company=str(r.get("Company") or "your team"))
            out.append(r)
    return sorted(out, key=lambda r: -r["Days since"])


def referrer_url(row: dict) -> str:
    """LinkedIn people search for someone at the company in the matching team (you open it logged in)."""
    title = str(row.get("Title") or "").lower()
    team = next((t for w, t in (("kyc", "compliance"), ("aml", "compliance"), ("compliance", "compliance"),
                                ("fraud", "fraud"), ("risk", "risk"), ("investigat", "investigations"),
                                ("support", "support"), ("community", "community"), ("research", "research"),
                                ("operations", "operations"), ("qa", "quality"), ("quality", "quality"),
                                ("engineer", "engineering"), ("developer", "engineering"))
                 if w in title), "recruiter")
    company = re.sub(r"\s*\(.*?\)|,? (inc|ltd|llc|limited|labs?)\.?$", "", str(row.get("Company") or ""), flags=re.I).strip()
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(f'{company} {team}')}"


def _write(wb, name: str, rows: list[dict], index: int, cols=COLS, hide=()):
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name, index)
    ws.append(cols)
    links = {"Apply link": ("Apply link", "Apply ↗"), "CV": ("_cv_link", None), "Find referrer": ("_referrer", "People ↗"),
             "Cover letter": ("_cl_link", None)}
    for r in rows:
        values = []
        for c in cols:
            if c in links and links[c][1]:
                values.append(links[c][1] if r.get(links[c][0]) else "")
            elif c == "Priority" and str(r.get("Status") or "New") in STATUS_LABEL:
                values.append(STATUS_LABEL[str(r["Status"])])
            elif c == "Status":
                values.append(r.get("Status") or "New")
            else:
                v = r.get(c, "")
                values.append("" if v is None else v)
        ws.append(values)
        for c, (src, _) in links.items():
            if c in cols and r.get(src):
                cell = ws.cell(row=ws.max_row, column=cols.index(c) + 1)
                cell.hyperlink = r[src]
                cell.font = LINK_FONT
    for i, c in enumerate(cols, 1):
        head = ws.cell(row=1, column=i)
        head.font, head.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        head.alignment = Alignment(vertical="center")
        ws.column_dimensions[head.column_letter].width = WIDTHS.get(c, 14)
        if c in HIDDEN or c in hide:
            ws.column_dimensions[head.column_letter].hidden = True
    # Status, Priority, Score and Title stay visible while you scroll right
    ws.freeze_panes = "E2" if "Priority" in cols else ("C2" if cols[0] == "Status" else "D2")
    last = ws.max_row
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(cols)).column_letter}{max(last, 2)}"
    if last >= 2 and "Score" in cols:
        score_col = ws.cell(row=1, column=cols.index("Score") + 1).column_letter
        ws.conditional_formatting.add(f"{score_col}2:{score_col}{last}", ColorScaleRule(
            start_type="num", start_value=25, start_color="F8696B", mid_type="num", mid_value=55,
            mid_color="FFEB84", end_type="num", end_value=85, end_color="63BE7B"))
    if last >= 2:
        status_col = ws.cell(row=1, column=cols.index("Status") + 1).column_letter
        last_col = ws.cell(row=1, column=len(cols)).column_letter
        # whole row coloured by Status, live: change the Status and the colour follows
        from openpyxl.formatting.rule import FormulaRule
        for st, colour in STATUS_FILLS.items():
            ws.conditional_formatting.add(f"A2:{last_col}{last}", FormulaRule(
                formula=[f'${status_col}2="{st}"'], fill=PatternFill("solid", fgColor=colour, bgColor=colour)))
        dv = DataValidation(type="list", formula1=f'"{",".join(STATUSES)}"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{status_col}2:{status_col}{last + 500}")
        flag_col = cols.index("Flags") + 1 if "Flags" in cols else None
        for r in range(2, last + 1):
            if flag_col and "SCAM" in str(ws.cell(row=r, column=flag_col).value or ""):
                ws.cell(row=r, column=flag_col).font = Font(bold=True, color="C00000")
            if "Priority" in cols:
                pc = ws.cell(row=r, column=cols.index("Priority") + 1)
                if str(pc.value or "").startswith("1"):
                    pc.font = Font(bold=True, color="006100")
                elif str(pc.value or "")[:1] in "✓★":
                    pc.font = Font(bold=True, color="375623")
        for msg_col in ("Referral message", "Follow-up message"):
            if msg_col not in cols:
                continue
            col = ws.cell(row=1, column=cols.index(msg_col) + 1).column_letter
            for r in range(2, last + 1):
                ws[f"{col}{r}"].alignment = Alignment(wrap_text=False, vertical="top")
    return ws


def _region_guard(rows, sc, bands):
    """Cap jobs you can't apply to from India, including rows left over from earlier runs.

    Scoring does this when a job is fetched, but All Jobs also holds rows that today's search
    didn't return; without this they keep an old, too-high score forever.
    """
    from jobhunter.scoring import _WORK_WORDS, _hits, _rx, out_of_reach

    cap = sc.get("region_locked_max_score")
    if not cap:
        return
    for row in rows:
        why = str(row.get("Why it matched") or "")
        if (row.get("Score") or 0) <= cap:
            continue
        title = str(row.get("Title") or "").lower()
        locale = out_of_reach(title, "", sc)
        loc_text = str(row.get("Location") or "").lower()
        if (not locale and _hits(title, ["intern", "internship", "interns", "trainee"]) and loc_text
                and not _hits(loc_text, sc["india_or_global_locations"]) and "remote" not in loc_text
                and str(row.get("Work mode") or "") != "Remote"):
            locale = "Internship abroad, these are usually for local students"
        if locale:
            row["Score"] = cap
            row["Priority"] = next((b["label"] for b in bands or [] if cap >= b["min"]), row.get("Priority"))
            if locale not in str(row.get("Flags") or ""):
                row["Flags"] = "; ".join(filter(None, [locale, row.get("Flags")]))
            continue
        if "hire globally" in why:
            continue
        loc = str(row.get("Location") or "").lower()
        if not loc or _hits(loc, sc["india_or_global_locations"]) or _hits(loc, sc.get("visa_typical_locations", [])):
            continue  # India/global, or a Gulf country where the employer sponsors the visa
        remote = str(row.get("Work mode") or "") == "Remote" or bool(_rx("remote").search(loc))
        place = re.sub(r"[^a-z ]+", " ", _WORK_WORDS.sub(" ", loc))
        if remote and re.search(r"[a-z]{2,}", place):
            row["Score"] = cap
            row["Priority"] = next((b["label"] for b in bands or [] if cap >= b["min"]), row.get("Priority"))
            flag = f"Remote but {place.split()[0].upper()}-only — you likely can't apply from India"
            if "can't apply from India" not in str(row.get("Flags") or ""):
                row["Flags"] = "; ".join(filter(None, [flag, row.get("Flags")]))


def _sorted(rows):
    # Rows flagged "not seen since … maybe closed" or closed on the apply page go below live ones:
    # closed Superteam bounties were sitting at the top of the Freelance tab.
    return sorted(rows, key=lambda r: ("not seen since" in str(r.get("Flags") or "")
                                       or str(r.get("Link check") or "").startswith("Closed"),
                                       -(r.get("Score") or 0), str(r.get("Source") or ""), str(r.get("Title") or "")))


def _queue_sorted(rows):
    """Best band first, then the newest day first (being among the first applicants matters), then score."""
    return sorted(rows, key=lambda r: (str(r.get("Priority") or "9"),
                                       -int(str(r.get("First seen") or "2000-01-01")[:10].replace("-", "") or 0),
                                       -(r.get("Score") or 0)))


TODAY_KEY_COL, TODAY_SAVED_COL = 24, 25          # hidden columns X and Y hold each job's key and saved status


def _read_today(ws) -> dict[str, dict]:
    """Status edits made on the Today tab (rows with a key in column X)."""
    rows = {}
    for r in range(1, ws.max_row + 1):
        key = ws.cell(row=r, column=TODAY_KEY_COL).value
        if key and key != "Key":
            rows[key] = {"Key": key, "Status": ws.cell(row=r, column=2).value or "New",
                         "Saved status": ws.cell(row=r, column=TODAY_SAVED_COL).value or "New",
                         "Notes": "", "Saved notes": "", "_has_saved": True}
    return rows


def _write_today(wb, plan: dict, index: int):
    """A calm one-screen plan: progress, what to do this hour, the next 5 jobs, follow-ups, one gig."""
    from jobhunter.plan import ROUTINE, headline
    ws = wb.create_sheet(TODAY_SHEET, index)
    widths = {"A": 4, "B": 14, "C": 46, "D": 22, "E": 24, "F": 9, "G": 22, "H": 22, "I": 10, "J": 70}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    for col in ("X", "Y"):
        ws.column_dimensions[col].hidden = True
    orange, dark, soft = PatternFill("solid", fgColor="F7931A"), HEADER_FILL, PatternFill("solid", fgColor="FFF2CC")
    white_bold = Font(bold=True, color="FFFFFF")
    dv = DataValidation(type="list", formula1=f'"{",".join(STATUSES)}"', allow_blank=True)
    ws.add_data_validation(dv)
    r = 1

    def put(row, col, value, font=None, fill=None, link=None, wrap=False):
        c = ws.cell(row=row, column=col, value=value)
        if font:
            c.font = font
        if fill:
            c.fill = fill
        if link:
            c.hyperlink, c.font = link, LINK_FONT
        c.alignment = Alignment(vertical="center", wrap_text=wrap)
        return c

    def band(row, text, fill):
        for col in range(1, 11):
            ws.cell(row=row, column=col).fill = fill
        put(row, 1, text, white_bold if fill is not soft else Font(bold=True), fill)

    put(r, 1, f"TODAY   {plan['weekday']} {plan['date']}   (updated {plan['time']}, refreshes every 15 minutes)",
        Font(bold=True, size=16))
    r += 1
    put(r, 1, headline(plan), Font(bold=True, size=13, color="B26505"))
    r += 1
    put(r, 1, f"Applied today {plan['applied_today']} of {plan['daily_target']}      This week {plan['applied_week']} of "
              f"{plan['weekly_target']}      Queue {plan['queue_size']} jobs ({plan['new_today']} new today)      "
              f"Follow-ups due {plan['followups_due']}", Font(size=11, color="444C5C"))
    r += 2
    s = plan["slot"]
    if s["name"]:
        band(r, f"RIGHT NOW   {s['time']}   {s['name']}", orange)
        r += 1
        put(r, 2, s["what"] + (f"   Target {s['target']}." if s["target"] else ""), Font(size=11), wrap=False)
        r += 2

    def job_table(title, rows, message_key, extra):
        nonlocal r
        band(r, title, dark)
        r += 1
        for col, h in enumerate(["#", "Status", "Job", "Company", "Where" if extra != "days" else "Applied", "Apply",
                                 "CV", "Cover letter", "People", "Why this job" if message_key != "Follow-up message"
                                 else "Message to send (put the name in place of NAME)"], 1):
            put(r, col, h, Font(bold=True), soft)
        r += 1
        if not rows:
            put(r, 3, "Nothing here right now.", Font(italic=True, color="666F80"))
            r += 2
            return
        first = r
        for i, row in enumerate(rows, 1):
            put(r, 1, i, Font(bold=True))
            put(r, 2, row.get("Status") or "New")
            put(r, 3, f"{row.get('Title')}  ({row.get('Score')})", Font(bold=True))
            put(r, 4, row.get("Company"))
            put(r, 5, f"{row.get('Days since')} days ago" if extra == "days" else row.get("Location"))
            if row.get("Apply link"):
                put(r, 6, "Apply ↗", link=row["Apply link"])
            if row.get("_cv_link"):
                put(r, 7, row.get("CV") or "CV", link=row["_cv_link"])
            if row.get("_cl_link"):
                put(r, 8, row.get("Cover letter") or "Cover letter", link=row["_cl_link"])
            if row.get("_referrer"):
                put(r, 9, "People ↗", link=row["_referrer"])
            detail = row.get(message_key) if message_key else ""
            if not detail:
                why = str(row.get("Why it matched") or "").split(" | ")[:3]
                flags = str(row.get("Flags") or "")
                detail = ", ".join(why) + (f".  Note {flags[:90]}" if flags else "")
            put(r, 10, detail, Font(size=10, color="444C5C"))
            ws.cell(row=r, column=TODAY_KEY_COL, value=row.get("Key"))
            ws.cell(row=r, column=TODAY_SAVED_COL, value=row.get("Status") or "New")
            r += 1
        dv.add(f"B{first}:B{r - 1}")
        for st, colour in STATUS_FILLS.items():
            from openpyxl.formatting.rule import FormulaRule
            ws.conditional_formatting.add(f"A{first}:J{r - 1}", FormulaRule(
                formula=[f'$B{first}="{st}"'], fill=PatternFill("solid", fgColor=colour, bgColor=colour)))
        r += 1

    job_table("1.  APPLY TO THESE, top first (set Status to Applied when done, the next job moves up)",
              plan["jobs"], None, "where")
    job_table("2.  FOLLOW UP ON THESE (applied 5 to 21 days ago, no answer yet)", plan["followups"],
              "Follow-up message", "days")
    band(r, "3.  ONE PAID GIG (proof of work that pays in days)", dark)
    r += 1
    g = plan.get("gig")
    if g:
        put(r, 3, f"{g.get('Title')}  ({g.get('Score')})", Font(bold=True))
        put(r, 4, g.get("Company"))
        put(r, 5, g.get("Salary") or "")
        if g.get("Apply link"):
            put(r, 6, "Open ↗", link=g["Apply link"])
        put(r, 10, f"Deadline {g.get('Deadline') or 'not given'}. More in the Freelance tab.", Font(size=10, color="444C5C"))
    else:
        put(r, 3, "No strong gig right now. The Freelance tab has the rest.", Font(italic=True, color="666F80"))
    r += 2
    band(r, "YOUR DAY  (PLAYBOOK routine, the current hour is highlighted)", dark)
    r += 1
    for start, end, name, what, target in ROUTINE[1:]:
        now_row = plan["slot"]["name"] == name
        put(r, 2, f"{start[0]:02d}.{start[1]:02d}", Font(bold=now_row))
        put(r, 3, name, Font(bold=True))
        put(r, 10, what + (f"  Target {target}." if target else ""), Font(size=10))
        if now_row:
            for col in range(1, 11):
                ws.cell(row=r, column=col).fill = soft
        r += 1
    r += 1
    put(r, 1, "How this works. Change the Status here or in any tab (Applied, Skip, Not relevant). The next check, "
              "within 15 minutes, moves the next job up. Telegram shows the same plan and has the same buttons.",
        Font(italic=True, size=9, color="666F80"))
    ws.freeze_panes = "A4"
    ws.sheet_view.showGridLines = False


def _write_earn(wb, platforms, index):
    """Static curated list of places to sign up and earn (kept from config/earn_platforms.yaml).
    Your Status and Notes are preserved."""
    old = {}
    if EARN_SHEET in wb.sheetnames:
        ws = wb[EARN_SHEET]
        header = [c.value for c in ws[1]]
        for cells in ws.iter_rows(min_row=2):
            row = {h: c.value for h, c in zip(header, cells) if h}
            if row.get("Platform"):
                old[row["Platform"]] = row
        del wb[EARN_SHEET]
    ws = wb.create_sheet(EARN_SHEET, index)
    ws.append(EARN_COLS)
    for p in sorted(platforms, key=lambda p: -p.get("fit", 0)):
        prev = old.get(p["platform"], {})
        ws.append([next((b["label"] for b in p.get("_bands", []) if p["fit"] >= b["min"]), p.get("priority", "")),
                   p.get("fit"), p["platform"], p.get("type", ""), p.get("what", ""), p.get("why", ""),
                   p.get("pay", ""), p.get("checked", ""), p.get("link", ""),
                   prev.get("Status") or "Not signed up", prev.get("Notes") or p.get("note", "")])
        link = ws.cell(row=ws.max_row, column=EARN_COLS.index("Link") + 1)
        if p.get("link"):
            link.hyperlink, link.font = p["link"], LINK_FONT
    for i, w in enumerate(EARN_WIDTHS, 1):
        c = ws.cell(row=1, column=i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        ws.column_dimensions[c.column_letter].width = w
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:K{max(ws.max_row, 2)}"
    dv = DataValidation(type="list", allow_blank=True,
                        formula1='"Not signed up,Signed up,Waiting approval,Working,Rejected,Skip"')
    ws.add_data_validation(dv)
    dv.add(f"J2:J{ws.max_row + 50}")
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=1).value or "").startswith("1"):
            ws.cell(row=r, column=1).font = Font(bold=True, color="006100")
        for col in (5, 6):
            ws.cell(row=r, column=col).alignment = Alignment(wrap_text=True, vertical="top")


def _write_health(wb, health_rows: list[list], index: int):
    if HEALTH_SHEET in wb.sheetnames:
        del wb[HEALTH_SHEET]
    ws = wb.create_sheet(HEALTH_SHEET, index)
    ws.append(HEALTH_COLS)
    for r in health_rows:
        ws.append(r)
    for i, w in enumerate([24, 13, 17, 17, 70, 13, 8, 10, 17], 1):
        c = ws.cell(row=1, column=i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
        ws.column_dimensions[c.column_letter].width = w
    for r in range(2, ws.max_row + 1):
        fails = ws.cell(row=r, column=8).value or 0
        if fails:
            for col in (1, 5, 8):
                ws.cell(row=r, column=col).font = Font(bold=True, color="C00000" if fails >= 3 else "9C5700")
    ws.freeze_panes = "B2"


def _office_running() -> bool:
    """Is LibreOffice or Excel actually running? (Windows only; assume yes if we can't tell.)"""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
    except Exception:
        return True
    return any(name in out for name in ("soffice.bin", "soffice.exe", "scalc.exe", "excel.exe"))


def _is_open(path: Path) -> bool:
    """Excel leaves a ~$ owner file, LibreOffice a .~lock file, while the workbook is open.

    If the app crashed or the laptop shut down with the file open, those lock files stay behind
    and every later run would save to a side file forever (happened 2026-09-21). A lock file only
    counts while LibreOffice/Excel is actually running; otherwise it is stale and is removed.
    """
    locks = [p for p in (path.with_name(f"~${path.name}"), path.with_name(f".~lock.{path.name}#")) if p.exists()]
    if not locks:
        return False
    if _office_running():
        return True
    for lock in locks:
        lock.unlink(missing_ok=True)
    print(f"Removed a stale lock file left by a closed/crashed spreadsheet app ({', '.join(l.name for l in locks)})")
    return False


def side_files(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.stem}_20*.xlsx"), key=lambda p: p.stat().st_mtime)


def adopt_side_files(path: Path) -> str | None:
    """Kept for old callers. Side files are now merged row by row inside save()."""
    return None


def sheet_rows(path: Path) -> dict[str, dict]:
    """Every job/gig row in the workbook, by key (used to sync the seen-jobs memory after a merge)."""
    wb = load_workbook(path)
    rows = {}
    for name in (ALL_SHEET, FREELANCE_SHEET):
        if name in wb.sheetnames:
            rows.update(_read(wb[name]))
    return rows


def _trim_log(ws, today: date):
    """Keep RUN_LOG_DAYS of run log. The 24x7 watcher adds a few rows every 15 minutes."""
    cutoff = (today - timedelta(days=RUN_LOG_DAYS)).isoformat()
    n = 0                                   # rows are appended in time order, so old ones are at the top
    while n + 2 <= ws.max_row and str(ws.cell(row=n + 2, column=1).value or "9") < cutoff:
        n += 1
    if n:
        ws.delete_rows(2, n)


def save(path: Path, jobs, first_seen: dict[str, str], today: date, log_rows: list[list],
         bands: list | None = None, closed_after_days: int = 3, earn_platforms: dict | None = None,
         dropped_keys: set | None = None, scoring: dict | None = None, found_at: dict | None = None,
         source_last_ok: dict | None = None, health_rows: list | None = None, enrich=None,
         queue_min_score: int = 55, remote_min_score: int = 35, urls: dict | None = None,
         actions: dict | None = None) -> SaveResult:
    """jobs: scored, de-duplicated, above min score. first_seen: key → ISO date (today for new ones).

    dropped_keys: jobs that were fetched this run but rejected (too low a score, scam flag). Their
    old rows are cleaned out so the sheet matches the current rules.
    source_last_ok: source name → ISO time of its last good run. A row is only marked "not seen since"
    when its source ran fine after the row was last seen (a blocked source says nothing about closure).
    enrich: callback(list of rows) run after merging and before writing (link checks, CV links).
    """
    dropped_keys, found_at, source_last_ok = dropped_keys or set(), found_at or {}, source_last_ok or {}
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = load_workbook(path) if path.exists() else Workbook()
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) == 1:
        del wb["Sheet"]
    day_name = today.isoformat()

    # ---- read every tab of the workbook and of any side files ----
    main_open = _is_open(path)
    sides = [s for s in side_files(path) if not _is_open(s)]
    tabs: list[tuple[str, dict]] = []                       # (tab name, rows) in priority order for edits
    all_rows = _read(wb[ALL_SHEET] if ALL_SHEET in wb.sheetnames else None)
    gig_rows = _read(wb[FREELANCE_SHEET] if FREELANCE_SHEET in wb.sheetnames else None)
    day_tabs = {s: _read(wb[s]) for s in wb.sheetnames if _is_day(s)}
    if TODAY_SHEET in wb.sheetnames:
        tabs.append((TODAY_SHEET, _read_today(wb[TODAY_SHEET])))
    for name in VIEW_SHEETS:
        if name in wb.sheetnames:
            tabs.append((name, _read(wb[name])))
    tabs += sorted(day_tabs.items(), key=lambda kv: kv[0], reverse=True)
    for side in sides:
        try:
            swb = load_workbook(side)
        except Exception:
            continue
        for name in [ALL_SHEET, FREELANCE_SHEET, *VIEW_SHEETS, *[s for s in swb.sheetnames if _is_day(s)]]:
            if name not in swb.sheetnames:
                continue
            srows = _read(swb[name])
            tabs.append((f"{side.name}:{name}", srows))
            if name == ALL_SHEET and TODAY_SHEET in swb.sheetnames:
                tabs.append((f"{side.name}:{TODAY_SHEET}", _read_today(swb[TODAY_SHEET])))
            if name == ALL_SHEET:
                for k, r in srows.items():
                    all_rows.setdefault(k, r)
            elif name == FREELANCE_SHEET:
                for k, r in srows.items():
                    gig_rows.setdefault(k, r)
            elif _is_day(name):
                day_tabs.setdefault(name, {})
                for k, r in srows.items():
                    day_tabs[name].setdefault(k, r)
    if day_name not in day_tabs:
        day_tabs[day_name] = {}

    # ---- apply links come from the database, never from the sheet's own hyperlinks ----
    if urls:
        for rows in [all_rows, gig_rows, *day_tabs.values()]:
            for k, r in rows.items():
                if urls.get(k):
                    r["Apply link"] = urls[k]

    # ---- resolve Status and Notes across all tabs before anything is replaced ----
    copies: dict[str, list[dict]] = {}
    for _, rows in tabs:
        for k, r in rows.items():
            copies.setdefault(k, []).append(r)
    for master in (all_rows, gig_rows):
        for k, r in master.items():
            before = str(r.get("Saved status") or "New") if r.get("_has_saved") else None
            r["Status"], r["Notes"] = resolve_user_fields(r, copies.get(k, []))
            if before is not None and str(r["Status"] or "New") != before:
                r["Status date"] = today.isoformat()      # for the Follow Ups tab
    for k, lst in copies.items():                              # rows only in a day tab (dropped from All Jobs)
        if k not in all_rows and k not in gig_rows:
            status, notes = resolve_user_fields(lst[0], lst[1:])
            for r in lst:
                r["Status"], r["Notes"] = status, notes
    # Buttons tapped in Telegram are the newest word on a job. They are re-applied on every save until one
    # reaches the main workbook (a side file alone could be overruled when it is merged back).
    applied_actions = []
    for k, act in (actions or {}).items():
        status, at, note = (tuple(act) + ("",))[:3]
        row = all_rows.get(k) or gig_rows.get(k)
        if row is None:
            continue
        if str(row.get("Status") or "New") != status:
            row["Status"], row["Status date"] = status, str(at)[:10]
        for part in str(note or "").split(" | "):
            if part and part not in str(row.get("Notes") or ""):
                row["Notes"] = " | ".join(filter(None, [str(row.get("Notes") or ""), part]))
        applied_actions.append(k)

    # ---- this run's jobs ----
    for job in jobs:
        target = gig_rows if job.kind == "freelance" else all_rows
        other = all_rows if job.kind == "freelance" else gig_rows
        old = target.get(job.key) or other.get(job.key)
        fresh = _job_row(job, first_seen[job.key], today, found_at.get(job.key, ""))
        if old:  # keep what you typed, the original first-seen date and the link check
            for f in ("Status", "Status date", "Notes", "First seen", "Found at", "Link check"):
                fresh[f] = old.get(f) or fresh.get(f)
        target[job.key] = fresh
        if first_seen[job.key] == day_name and job.kind != "freelance":
            day_tabs[day_name][job.key] = fresh

    for name, rows in (("All Jobs", all_rows), ("Freelance", gig_rows)):
        for r in rows.values():
            r["_kind"] = "freelance" if name == "Freelance" else r.get("_kind", "job")

    for row in [*all_rows.values(), *gig_rows.values()]:
        if not row.get("Priority") and row.get("Score") is not None:  # rows written before the Priority column existed
            row["Priority"] = next((b["label"] for b in bands or [] if row["Score"] >= b["min"]), "")
        last_seen = str(row.get("Last seen") or "")
        if last_seen and (today - date.fromisoformat(last_seen[:10])).days >= closed_after_days:
            base = str(row.get("Source") or "").split(":")[0].strip()
            ok = source_last_ok.get(base)
            checked_since = ok is None or ok[:10] > last_seen[:10]
            if checked_since and "not seen since" not in str(row.get("Flags") or ""):
                row["Flags"] = "; ".join(filter(None, [f"not seen since {last_seen[:10]} — maybe closed", row.get("Flags")]))

    fresh_gigs = {j.key for j in jobs if j.kind == "freelance"}
    for key in set(gig_rows) & set(all_rows):  # re-classified since an earlier run: drop the wrong copy
        keep, drop = (gig_rows, all_rows) if key in fresh_gigs else (all_rows, gig_rows)
        old = drop.pop(key)
        # Keep your Status/Notes. An Applied job once moved to Freelance as "New"
        # when remoteok described it as contract work (2026-09-24).
        if old.get("Status") not in (None, "", "New") and keep[key].get("Status") in (None, "", "New"):
            keep[key]["Status"], keep[key]["Notes"] = old["Status"], old.get("Notes") or keep[key].get("Notes")

    # Rows re-checked this run that no longer qualify (score fell, gig turned out to be a scam,
    # or it was misfiled) are removed, unless you have already acted on them.
    for sheet in (gig_rows, all_rows, day_tabs[day_name]):
        for key in [k for k in sheet if k in dropped_keys and sheet[k].get("Status") in (None, "", "New")]:
            del sheet[key]

    # drop freelance rows whose deadline has passed, unless you already engaged with them
    gig_rows = {k: r for k, r in gig_rows.items()
                if not (r.get("Deadline") and str(r["Deadline"])[:10] < today.isoformat()
                        and (r.get("Status") in (None, "", "New")))}

    _region_guard(list(all_rows.values()), scoring or {}, bands)

    master_rows = [*all_rows.values(), *gig_rows.values()]
    mark_applied_duplicates(master_rows)
    if enrich:
        enrich(master_rows)
    for r in master_rows:   # the band always follows the score (the sheet shows "✓ Applied" instead once acted on)
        if r.get("Score") is not None:
            r["Priority"] = next((b["label"] for b in bands or [] if (r["Score"] or 0) >= b["min"]), r.get("Priority"))
    for r in master_rows:
        r["_referrer"] = referrer_url(r)

    # every tab is a view of the master rows (a day tab keeps its own copy of rows no longer in All Jobs)
    def view(k, r):
        m = all_rows.get(k) or gig_rows.get(k)
        return m if m is not None else r

    for rows in day_tabs.values():
        for k in list(rows):
            rows[k] = view(k, rows[k])
    written = [*master_rows, *[r for rows in day_tabs.values() for r in rows.values()]]
    for r in written:
        r["Saved status"], r["Saved notes"] = r.get("Status") or "New", r.get("Notes") or ""

    queue = [r for r in master_rows if queue_ok(r, queue_min_score)]
    if queue:
        from jobhunter.cv import load_config, referral_message
        cvcfg = load_config()
        for r in queue:
            r["Referral message"] = referral_message(r, cvcfg)
    remote = [r for r in all_rows.values() if remote_ok(r, remote_min_score)]
    follow = follow_ups(master_rows, today)

    from jobhunter import plan as planner
    today_plan = planner.build(master_rows, today)
    for name in [TODAY_SHEET, QUEUE_SHEET, FOLLOW_SHEET, REMOTE_SHEET, FREELANCE_SHEET, ALL_SHEET]:
        if name in wb.sheetnames:
            del wb[name]
    _write_today(wb, today_plan, 0)
    _write(wb, QUEUE_SHEET, _queue_sorted(queue), 1, cols=QUEUE_COLS)
    _write(wb, FOLLOW_SHEET, follow, 2, cols=FOLLOW_COLS)
    _write(wb, REMOTE_SHEET, _sorted(remote), 3)
    _write(wb, FREELANCE_SHEET, _sorted(gig_rows.values()), 4)
    _write(wb, ALL_SHEET, _sorted(all_rows.values()), 5)
    for i, name in enumerate(sorted(day_tabs, reverse=True)):
        _write(wb, name, _sorted(day_tabs[name].values()), 6 + i)
    if earn_platforms:
        for p in earn_platforms.get("platforms", []):
            p["_bands"] = bands or []
        _write_earn(wb, earn_platforms.get("platforms", []), len(wb.sheetnames))
    if health_rows is not None:
        _write_health(wb, health_rows, len(wb.sheetnames))

    if LOG_SHEET not in wb.sheetnames:
        log = wb.create_sheet(LOG_SHEET)
        log.append(LOG_COLS)
        for i, w in enumerate([18, 30, 12, 16, 10, 90], 1):
            log.cell(1, i).font, log.cell(1, i).fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
            log.column_dimensions[log.cell(1, i).column_letter].width = w
    log = wb[LOG_SHEET]
    for row in log_rows:
        log.append(row)
    _trim_log(log, today)
    for name in (EARN_SHEET, HEALTH_SHEET, LOG_SHEET):
        if name in wb.sheetnames:
            wb.move_sheet(name, offset=len(wb.sheetnames) - 1 - wb.sheetnames.index(name))
    wb.active = wb.sheetnames.index(TODAY_SHEET)
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = ws.title == TODAY_SHEET

    target = path
    if main_open:  # LibreOffice doesn't lock the file, so saving would silently fight with your open copy
        target = path.with_name(f"{path.stem}_{datetime.now():%Y-%m-%d_%H%M}.xlsx")
    try:
        saved = _save_safely(wb, target)
    except PermissionError:  # open in Excel, which does lock it
        saved = _save_safely(wb, path.with_name(f"{path.stem}_{datetime.now():%Y-%m-%d_%H%M%S}.xlsx"))
    # everything in the side files is now in the file just written: remove them (the newest one is
    # the file just written when the main workbook is open)
    for side in sides:
        if side != saved:
            side.unlink(missing_ok=True)
    rows_by_key = {r["Key"]: r for r in master_rows if r.get("Key")}
    return SaveResult(saved, rows_by_key, [s.name for s in sides if s != saved], today_plan,
                      applied_actions if saved == path else [])


def _save_safely(wb, path: Path) -> Path:
    """Write to a temp file beside the target, then swap it in, keeping one .bak.

    Saving straight over the workbook means a crash (a full disk, for example) leaves it corrupt.
    Python's temp folder lives on C:, so it is forced next to the output file: if C: is full,
    the save must still work.
    """
    free_mb = shutil.disk_usage(path.parent).free // (1024 * 1024)
    if free_mb < 50:
        raise OSError(f"only {free_mb} MB free on {path.drive or path.parent} — free up space and run again")
    old_tempdir = tempfile.tempdir
    tempfile.tempdir = str(path.parent)          # openpyxl writes sheet parts to temp files
    tmp = path.with_name(path.stem + ".saving.tmp")
    try:
        wb.save(tmp)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".bak.xlsx"))
        os.replace(tmp, path)                     # atomic: the workbook is never half-written
    finally:
        tempfile.tempdir = old_tempdir
        tmp.unlink(missing_ok=True)
    return path
