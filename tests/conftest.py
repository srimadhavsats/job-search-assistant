"""Shared test helpers. Tests never touch the real workbook, database or network."""
import sys
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def profile():
    return yaml.safe_load((ROOT / "config" / "profile.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sc(profile):
    return profile["scoring"]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Back-off pauses would make tests slow; count them instead."""
    import time as _time
    slept = []
    monkeypatch.setattr(_time, "sleep", lambda s: slept.append(s))
    from jobhunter import net
    net.reset_breakers()
    return slept


def mock_client_factory(handler, **retry):
    """A util.http_client replacement whose requests go to `handler(request) -> httpx.Response`."""
    from jobhunter.net import RetryClient

    def factory(log=None, **kw):
        opts = {**retry, **kw}
        return RetryClient(transport=httpx.MockTransport(handler), log=log, follow_redirects=True, **opts)
    return factory


@pytest.fixture
def store(tmp_path):
    from jobhunter.store import SeenStore
    s = SeenStore(tmp_path / "seen.sqlite")
    yield s
    try:
        s.close()
    except Exception:
        pass
