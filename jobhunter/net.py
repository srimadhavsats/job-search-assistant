"""Resilient HTTP shared by every source (added 2026-09-25).

The 18:30 run on 2026-09-25 lost all ~390 web3.career jobs because one page read timed out and the
whole source raised. Every client from `util.http_client()` is now a `RetryClient`:

  - network errors (timeouts, resets, DNS hiccups) are retried with growing pauses
  - HTTP 429 and 5xx are retried, honouring the site's Retry-After header (capped)
  - a host that keeps failing within one run is skipped for the rest of that run (circuit breaker),
    so a dead site costs seconds, not ten minutes of timeouts
  - the final failure still raises / returns the last response, so callers keep their own logic

`browser_get()` is the last resort for pages behind a bot check (Cloudflare "Just a moment"): it
opens the page in the installed Google Chrome, headless, the way the Naukri source does.
"""
from __future__ import annotations

import random
import threading
import time
from urllib.parse import urlparse

import httpx

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526}
BLOCK_MARKERS = ("just a moment", "cf-chl", "challenge-platform", "captcha", "access denied",
                 "attention required", "are you a robot", "request blocked")

_lock = threading.Lock()
_host_failures: dict[str, int] = {}
_announced: set[str] = set()
BREAKER_LIMIT = 4          # consecutive fully-failed requests to one host before it is skipped this run


class HostSkipped(httpx.TransportError):
    """Raised instead of trying a host that has failed repeatedly in this run."""


def _host(url) -> str:
    return urlparse(str(url)).netloc.lower()


def host_ok(url) -> bool:
    with _lock:
        return _host_failures.get(_host(url), 0) < BREAKER_LIMIT


def _record(url, ok: bool):
    with _lock:
        h = _host(url)
        _host_failures[h] = 0 if ok else _host_failures.get(h, 0) + 1


def reset_breakers():
    with _lock:
        _host_failures.clear()
        _announced.clear()


def looks_blocked(resp: httpx.Response | None) -> bool:
    if resp is None:
        return False
    if resp.status_code in (401, 403, 429, 503) or resp.status_code >= 520:
        head = resp.text[:6000].lower()
        return any(m in head for m in BLOCK_MARKERS) or resp.status_code in (403, 429)
    return False


def _retry_after(resp: httpx.Response, fallback: float, cap: float) -> float:
    value = resp.headers.get("retry-after", "")
    try:
        return min(float(value), cap)
    except ValueError:
        return fallback


class RetryClient(httpx.Client):
    """httpx.Client whose requests retry on network errors, 429 and 5xx.

    tries       total attempts per request
    backoff     pause before attempt 2, 3, … (seconds, randomised ±30 %)
    retry_429   False when the caller runs its own rate-limit back-off (LinkedIn)
    log         optional callable for "retrying …" messages
    """

    def __init__(self, *args, tries: int = 4, backoff=(3, 10, 30, 60), retry_429: bool = True,
                 max_wait: float = 180, log=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tries, self.backoff, self.retry_429 = tries, tuple(backoff), retry_429
        self.max_wait, self.log = max_wait, log

    def _say(self, msg: str):
        if self.log:
            try:
                self.log(msg)
            except Exception:
                pass

    def request(self, method, url, *args, **kwargs):
        if not host_ok(url):
            h = _host(url)
            with _lock:
                first = h not in _announced
                _announced.add(h)
            if first:
                self._say(f"WARNING {h} skipped for the rest of this run after repeated failures")
            raise HostSkipped(f"{h} skipped after repeated failures")
        last_exc, resp = None, None
        for attempt in range(1, self.tries + 1):
            try:
                resp = super().request(method, url, *args, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                last_exc, resp = e, None
                if attempt < self.tries:
                    wait = self.backoff[min(attempt - 1, len(self.backoff) - 1)] * random.uniform(0.7, 1.3)
                    self._say(f"retry {attempt} after {type(e).__name__} on {_host(url)} (waiting {wait:.0f}s)")
                    time.sleep(wait)
                continue
            retryable = resp.status_code in RETRY_STATUS and (self.retry_429 or resp.status_code != 429)
            if not retryable:
                _record(url, True)
                return resp
            if attempt < self.tries:
                base = self.backoff[min(attempt - 1, len(self.backoff) - 1)]
                wait = _retry_after(resp, base, self.max_wait) * random.uniform(0.9, 1.3)
                self._say(f"retry {attempt} after HTTP {resp.status_code} on {_host(url)} (waiting {wait:.0f}s)")
                time.sleep(wait)
        _record(url, False)
        if resp is not None:
            return resp          # caller sees the last 429/5xx and decides
        raise last_exc


_browser_lock = threading.Lock()


def browser_get(url: str, wait_ms: int = 4000, timeout_ms: int = 45000) -> str | None:
    """Open a page in installed Google Chrome (headless, normal user agent) and return its HTML.

    Used only after plain HTTP was refused by a bot check. One page at a time: Chrome is heavy.
    Returns None if Chrome or Playwright is missing or the page still shows a challenge."""
    from jobhunter.util import UA
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with _browser_lock:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=True,
                                            args=["--disable-blink-features=AutomationControlled"])
                try:
                    page = browser.new_page(user_agent=UA, locale="en-US")
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(wait_ms)
                    html = page.content()
                finally:
                    browser.close()
        except Exception:
            return None
    head = html[:6000].lower()
    if any(m in head for m in ("just a moment", "cf-chl", "attention required")):
        return None
    return html
