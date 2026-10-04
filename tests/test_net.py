"""Retries, back-off and the per-host circuit breaker (jobhunter/net.py)."""
import httpx
import pytest

from jobhunter import net
from tests.conftest import mock_client_factory


def test_429_then_ok_is_retried(no_sleep):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "7"}) if len(calls) == 1 else httpx.Response(200, text="ok")

    with mock_client_factory(handler)() as c:
        r = c.get("https://example.org/a")
    assert r.status_code == 200 and len(calls) == 2
    assert 6 <= no_sleep[0] <= 10          # honours Retry-After (with a little jitter)


def test_timeouts_are_retried_then_raised():
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=req)

    with mock_client_factory(handler, tries=3)() as c:
        with pytest.raises(httpx.ReadTimeout):
            c.get("https://slow.example/a")
    assert len(calls) == 3


def test_timeout_then_success_recovers():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("reset", request=req)
        return httpx.Response(200, json={"ok": True})

    with mock_client_factory(handler)() as c:
        assert c.get("https://flaky.example/").json() == {"ok": True}


def test_429_not_retried_when_caller_handles_it():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429)

    with mock_client_factory(handler, retry_429=False)() as c:
        assert c.get("https://linkedin.example/").status_code == 429
    assert len(calls) == 1


def test_404_is_returned_immediately():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404)

    with mock_client_factory(handler)() as c:
        assert c.get("https://x.example/gone").status_code == 404
    assert len(calls) == 1


def test_circuit_breaker_skips_dead_host_after_repeated_failures():
    calls = []

    def handler(req):
        calls.append(req.url.host)
        raise httpx.ConnectTimeout("down", request=req)

    msgs = []
    with mock_client_factory(handler, tries=1)(log=msgs.append) as c:
        for _ in range(net.BREAKER_LIMIT):
            with pytest.raises(httpx.ConnectTimeout):
                c.get("https://dead.example/")
        with pytest.raises(net.HostSkipped):
            c.get("https://dead.example/other")
        # other hosts are unaffected
        with pytest.raises(httpx.ConnectTimeout):
            c.get("https://alive.example/")
    assert calls.count("dead.example") == net.BREAKER_LIMIT
    assert any("skipped for the rest of this run" in m for m in msgs)


def test_looks_blocked():
    assert net.looks_blocked(httpx.Response(403, text="<title>Just a moment...</title>"))
    assert net.looks_blocked(httpx.Response(429, text=""))
    assert not net.looks_blocked(httpx.Response(200, text="Just a moment"))
    assert not net.looks_blocked(httpx.Response(404, text="nope"))
