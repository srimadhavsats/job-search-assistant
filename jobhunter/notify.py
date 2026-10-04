"""Alerts for new jobs (added 2026-09-25): Windows pop-ups, Telegram, ntfy. Settings in config/notify.yaml.

Only jobs worth acting on ping you: score at or above min_score (a bit lower for remote jobs open to
India), status New, not region-locked, language-locked or closed. Each job pings once, ever
(seen_jobs.sqlite, table notified). Pop-ups have "Open job" and "Open CV" buttons. Telegram messages
carry the apply link, why it matched, and the CV PDF itself, so you can apply from your phone.
Alert text avoids colons, semicolons and dashes, like everything else written for you.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

ROOT = Path(__file__).resolve().parent.parent
POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_BANNED = re.compile(r"\s*[;:—–→·|]\s*")


def load_config() -> dict:
    p = ROOT / "config" / "notify.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    tg = cfg.setdefault("telegram", {}) or {}
    secret = {}
    sp = ROOT / "config" / "telegram.yaml"          # written by setup_telegram.bat
    if sp.exists():
        secret = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}
    tg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN") or secret.get("bot_token") or tg.get("bot_token") or ""
    tg["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID") or str(secret.get("chat_id") or tg.get("chat_id") or "")
    cfg["telegram"] = tg
    return cfg


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", _BANNED.sub(", ", str(text or ""))).strip(" ,")


def worth_alert(row: dict, cfg: dict) -> bool:
    from jobhunter.excel import is_remote, locked
    if str(row.get("Status") or "New") != "New":
        return False
    if cfg.get("only_applicable", True) and locked(row):
        return False
    score = row.get("Score") or 0
    if row.get("_kind") == "freelance":
        return score >= cfg.get("freelance_min_score", 65)
    need = cfg.get("min_score", 60) - (cfg.get("remote_bonus", 0) if is_remote(row) else 0)
    return score >= need


def _cv_path(row: dict) -> Path | None:
    link = row.get("_cv_link")
    if not link:
        return None
    p = (ROOT / "output" / link).resolve()
    return p if p.exists() else None


def _line(row: dict) -> str:
    where = plain(row.get("Location") or row.get("Work mode") or "")
    return plain(f"{row.get('Score')}  {row.get('Title')} at {row.get('Company') or 'unknown company'}") + (f", {where}" if where else "")


def windows_popup(title: str, body: str, open_url: str = "", cv: Path | None = None) -> bool:
    if os.name != "nt":
        return False
    actions = ""
    if open_url:
        actions += f'<action content="Open job" activationType="protocol" arguments="{escape(open_url, {chr(34): "&quot;"})}"/>'
    if cv:
        actions += f'<action content="Open CV" activationType="protocol" arguments="{escape(cv.as_uri(), {chr(34): "&quot;"})}"/>'
    launch = f' activationType="protocol" launch="{escape(open_url, {chr(34): "&quot;"})}"' if open_url else ""
    xml = (f'<toast{launch}><visual><binding template="ToastGeneric"><text>{escape(title)}</text>'
           f'<text>{escape(body[:250])}</text></binding></visual>'
           + (f"<actions>{actions}</actions>" if actions else "") + "</toast>")
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{xml}
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{POWERSHELL_APP_ID}').Show($toast)
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", encoded], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def telegram(cfg: dict, text: str, document: Path | None = None) -> bool:
    tg = cfg.get("telegram") or {}
    token, chat = tg.get("bot_token"), tg.get("chat_id")
    if not token or not chat:
        return False
    from jobhunter.util import http_client
    try:
        with http_client(tries=3) as c:
            r = c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       data={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
            ok = r.status_code == 200
            if ok and document and tg.get("send_cv_pdf", True):
                with open(document, "rb") as fh:
                    c.post(f"https://api.telegram.org/bot{token}/sendDocument", data={"chat_id": chat},
                           files={"document": (document.name, fh, "application/pdf")})
            return ok
    except Exception:
        return False


def telegram_chat_id(token: str) -> str | None:
    """After you message your bot once, its updates contain your chat id."""
    from jobhunter.util import http_client
    with http_client(tries=2) as c:
        data = c.get(f"https://api.telegram.org/bot{token}/getUpdates").json()
    for upd in reversed(data.get("result", [])):
        chat = ((upd.get("message") or upd.get("channel_post") or {}).get("chat") or {})
        if chat.get("id"):
            return str(chat["id"])
    return None


def ntfy(cfg: dict, title: str, body: str, url: str = "") -> bool:
    topic = cfg.get("ntfy_topic")
    if not topic:
        return False
    from jobhunter.util import http_client
    try:
        with http_client(tries=2) as c:
            headers = {"Title": title.encode("ascii", "ignore").decode()}
            if url:
                headers["Click"] = url
            return c.post(f"https://ntfy.sh/{topic}", content=body.encode("utf-8"), headers=headers).status_code == 200
    except Exception:
        return False


def _tg_html(row: dict) -> str:
    h = lambda s: escape(plain(s))
    parts = [f"<b>{h(row.get('Title'))}</b>", f"{h(row.get('Company'))}, {h(row.get('Location') or row.get('Work mode'))}",
             f"Score {row.get('Score')}, {h(row.get('Priority'))}"]
    if row.get("Salary"):
        parts.append(f"Pay {h(row.get('Salary'))}")
    if row.get("CV"):
        parts.append(f"CV to send is {h(row.get('CV'))}")
    if row.get("Flags"):
        parts.append(f"Note {h(str(row.get('Flags'))[:160])}")
    parts.append(f'<a href="{escape(str(row.get("Apply link") or ""))}">Open the job</a>')
    return "\n".join(parts)


def new_jobs(rows: dict, new_keys: set, store, log=print, cfg: dict | None = None) -> int:
    """Alert for new rows worth acting on. rows: key -> row as written to the workbook."""
    cfg = cfg or load_config()
    todo = [rows[k] for k in new_keys if k in rows and worth_alert(rows[k], cfg) and not store.was_notified(k)]
    if not todo:
        return 0
    todo.sort(key=lambda r: -(r.get("Score") or 0))
    sent_any = False
    if cfg.get("windows_popup", True):
        limit = cfg.get("max_popups_per_check", 4)
        if len(todo) > limit:
            body = "  ".join(_line(r) for r in todo[:5])
            sent_any |= windows_popup(f"{len(todo)} new jobs for you", body,
                                      (ROOT / "output" / "Jobs.xlsx").resolve().as_uri())
        else:
            for r in todo:
                sent_any |= windows_popup(plain(f"New job {r.get('Score')}, {r.get('Company')}"),
                                          plain(f"{r.get('Title')}. {r.get('Location') or ''}. CV {r.get('CV') or ''}"),
                                          str(r.get("Apply link") or ""), _cv_path(r))
    from jobhunter import tgbot
    for r in todo[:15]:
        if (cfg.get("telegram") or {}).get("bot_token"):
            sent_any |= tgbot.push_card(r, "New job for you")   # with Applied, Skip, CV and cover letter buttons
        sent_any |= ntfy(cfg, plain(f"New job {r.get('Score')} {r.get('Company')}"), _line(r), str(r.get("Apply link") or ""))
    store.mark_notified([(r["Key"], r.get("Score") or 0) for r in todo])
    log(f"alerted you about {len(todo)} new job(s)" + ("" if sent_any else " (no alert channel answered)"))
    return len(todo)


def source_problems(states: list[dict], store, log=print, cfg: dict | None = None) -> int:
    """One alert a day per source that keeps failing (blocked, site changed)."""
    cfg = cfg or load_config()
    limit = cfg.get("source_failure_alert_after", 3)
    bad = [s for s in states if (s.get("fails") or 0) >= limit]
    sent = 0
    for s in bad:
        key = f"health:{s['name']}:{date.today().isoformat()}"
        if store.was_notified(key):
            continue
        msg = plain(f"{s['name']} failed {s['fails']} checks in a row. Last result {s.get('last_status') or ''}")
        windows_popup(plain(f"Job search, {s['name']} needs a look"), msg)
        telegram(cfg, escape(msg))
        store.mark_notified([(key, 0)])
        sent += 1
    if sent:
        log(f"sent {sent} source health alert(s)")
    return sent
