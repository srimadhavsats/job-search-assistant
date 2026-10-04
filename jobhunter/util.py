from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def http_client(log=None, **retry) -> httpx.Client:
    """A client that retries network errors, 429 and 5xx (see net.RetryClient). Pass the source's
    log to see retries in the run output, and retry options (tries, backoff, retry_429) to tune."""
    from jobhunter.net import RetryClient
    return RetryClient(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                       follow_redirects=True, timeout=httpx.Timeout(30, connect=15), log=log, **retry)


def html_to_text(s: str | None, limit: int = 6000) -> str:
    if not s:
        return ""
    if "&lt;" in s:
        s = html.unescape(s)
    text = BeautifulSoup(s, "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:limit]


def to_date(value) -> date | None:
    """Accepts ISO strings, epoch ms/seconds, datetime/date, struct_time. Returns None if unknown."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            v = float(value)
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc).date()
        if hasattr(value, "tm_year"):
            return date(value.tm_year, value.tm_mon, value.tm_mday)
        s = str(value).strip().replace(" ", "T", 1) if re.match(r"\d{4}-\d{2}-\d{2} ", str(value)) else str(value)
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (ValueError, OSError, OverflowError):
        return None


def detect_work_mode(*texts: str) -> str:
    t = " ".join(x for x in texts if x).lower()
    if "hybrid" in t:
        return "Hybrid"
    if re.search(r"\bremote\b|work from home|wfh|anywhere", t):
        return "Remote"
    return ""
