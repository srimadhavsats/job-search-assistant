"""What to do now (added 2026-09-26). One plan, shown in two places: the Today tab and the Telegram bot.

It never shows everything. It picks a handful of next actions from the workbook: the next jobs to apply
to (top of the Apply Queue), follow-ups that are due, one paid gig, and the PLAYBOOK section 4 routine
slot for the current time of day, with progress against the daily and weekly targets.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

# The daily routine shown on the Today tab and in the bot. A generic default, change it to fit the
# owner's day and the routine in their PLAYBOOK.md (start, end, name, what to do, target).
ROUTINE = [
    ((0, 0), (9, 30), "Morning", "The watcher runs the full morning search after 09.30. Start with applications at 10.30.", ""),
    ((9, 30), (10, 30), "Get ready", "Check email (also Spam and Promotions), LinkedIn and Naukri messages. Reply to recruiters first.", ""),
    ((10, 30), (11, 30), "Apply", "Apply to the jobs below with the linked CV and cover letter. Send each one's referral message.", "5 applications"),
    ((11, 30), (13, 30), "Referrals", "Ask people at the companies you applied to for a referral. Use the People link and the ready message.", "3 requests"),
    ((13, 30), (14, 30), "Break", "Lunch and rest. Consistency beats bursts.", ""),
    ((14, 30), (16, 30), "Profile and network", "Refresh your Naukri and LinkedIn profiles, reply to recruiters and message former colleagues.", "3 messages"),
    ((16, 30), (19, 0), "Skills and interviews", "Practise interview answers or learn one skill the jobs keep asking for.", "1 hour"),
    ((19, 0), (20, 0), "Follow ups", "Send the follow ups that are due (Follow Ups tab).", ""),
    ((20, 0), (24, 0), "Night check", "Check email (also Spam and Promotions) and job site messages. Reply within hours.", ""),
]
DAILY_TARGET, WEEKLY_TARGET = 5, 25


def slot(now: datetime) -> dict:
    hm = (now.hour, now.minute)
    for start, end, name, what, target in ROUTINE:
        if start <= hm < end:
            return {"name": name, "what": what, "target": target,
                    "time": f"{start[0]:02d}.{start[1]:02d} to {min(end[0], 23):02d}.{end[1] if end[0] < 24 else 59:02d}"}
    return {"name": "", "what": "", "target": "", "time": ""}


def _day(value) -> str:
    return str(value or "")[:10]


def build(rows: list[dict], today: date | None = None, now: datetime | None = None, n_jobs: int = 5) -> dict:
    """rows: master rows (All Jobs and Freelance) as written to the workbook."""
    from jobhunter.excel import _queue_sorted, follow_ups, locked, queue_ok
    now = now or datetime.now()
    today = today or now.date()
    monday = today - timedelta(days=today.weekday())
    applied = [r for r in rows if str(r.get("Status") or "") in ("Applied", "Interview", "Offer")]
    applied_today = [r for r in applied if _day(r.get("Status date")) == today.isoformat()]
    applied_week = [r for r in applied if _day(r.get("Status date")) >= monday.isoformat()]
    queue = _queue_sorted([r for r in rows if queue_ok(r)])
    fups = follow_ups(rows, today)
    gigs = sorted([r for r in rows if r.get("_kind") == "freelance" and str(r.get("Status") or "New") == "New"
                   and (r.get("Score") or 0) >= 70 and not locked(r)
                   and (not r.get("Deadline") or _day(r.get("Deadline")) >= today.isoformat())],
                  key=lambda r: -(r.get("Score") or 0))
    new_today = [r for r in queue if _day(r.get("First seen")) == today.isoformat()]
    sunday = today.weekday() == 6
    return {
        "date": today.isoformat(), "time": now.strftime("%H.%M"), "weekday": today.strftime("%A"),
        "slot": slot(now), "sunday": sunday,
        "applied_today": len(applied_today), "applied_week": len(applied_week),
        "daily_target": DAILY_TARGET, "weekly_target": WEEKLY_TARGET,
        "queue_size": len(queue), "new_today": len(new_today), "followups_due": len(fups),
        "jobs": queue[:n_jobs], "followups": fups[:3], "gig": gigs[0] if gigs else None,
        "queue": queue,
    }


def headline(p: dict) -> str:
    left = max(0, p["daily_target"] - p["applied_today"])
    if p["sunday"]:
        return "Sunday. Rest, and do the weekly review (count applications, DMs and replies per lane)."
    if left:
        return f"Apply to {left} more job{'s' if left != 1 else ''} today. Start with number 1 below."
    return "Daily application target done. Now follow-ups, then the routine for this hour."


def text(p: dict, with_jobs: bool = True) -> str:
    """Plain text version for Telegram (HTML-escaped by the caller)."""
    lines = [f"{p['weekday']} {p['time']}", headline(p), "",
             f"Applied today {p['applied_today']} of {p['daily_target']}, this week {p['applied_week']} of {p['weekly_target']}",
             f"Queue {p['queue_size']} jobs ({p['new_today']} new today), follow-ups due {p['followups_due']}", ""]
    s = p["slot"]
    if s["name"]:
        lines += [f"Right now ({s['time']}) {s['name']}", s["what"] + (f" Target {s['target']}." if s["target"] else ""), ""]
    if with_jobs and p["jobs"]:
        lines.append("Next jobs")
        for i, r in enumerate(p["jobs"], 1):
            lines.append(f"{i}. {r.get('Title')} at {r.get('Company')} ({r.get('Score')})")
    if p["followups"]:
        lines += ["", "Follow up"]
        for r in p["followups"]:
            lines.append(f"{r.get('Title')} at {r.get('Company')}, applied {r.get('Days since')} days ago")
    if p["gig"]:
        g = p["gig"]
        lines += ["", f"Paid gig {g.get('Title')} ({g.get('Salary') or 'see link'})"]
    return "\n".join(lines)
