import json
import os
import stat
import subprocess
import sys
import textwrap
import time

import pytest

from gpa_analyzer import analyzer as gpa
from gpa_analyzer import app as web
from gpa_analyzer.analyzer import NtustGradeScraper


@pytest.fixture
def scraper_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    created = []

    def make(username, password):
        s = NtustGradeScraper(username, password)
        created.append(s)
        return s

    yield make
    for s in created:
        s.close()


def test_cache_key_is_bound_to_the_password(scraper_factory):
    right = scraper_factory("B11234567", "correct-password")
    wrong = scraper_factory("B11234567", "wrong-password")
    assert right._cache_key != wrong._cache_key


def test_cached_cookies_are_not_served_to_a_different_password(scraper_factory):
    """Regression: a cache hit must never stand in for authentication."""
    right = scraper_factory("B11234567", "correct-password")
    right.client.cookies.set("StuScoreQueryServ", "session-value")
    right._store_cookies()

    assert right._load_cached_cookies() is True

    wrong = scraper_factory("B11234567", "wrong-password")
    assert wrong._load_cached_cookies() is False
    assert wrong.client.cookies.get("StuScoreQueryServ") is None


def test_cached_cookies_expire(scraper_factory, monkeypatch):
    s = scraper_factory("B11234567", "pw")
    s.client.cookies.set("StuScoreQueryServ", "session-value")
    s._store_cookies()

    far_future = time.time() + 2 * gpa.COOKIE_CACHE_TTL
    monkeypatch.setattr(time, "time", lambda: far_future)
    fresh = scraper_factory("B11234567", "pw")
    assert fresh._load_cached_cookies() is False


def test_dropping_cached_cookies_removes_only_that_entry(scraper_factory):
    a = scraper_factory("A", "pw")
    b = scraper_factory("B", "pw")
    for s in (a, b):
        s.client.cookies.set("StuScoreQueryServ", "v")
        s._store_cookies()

    a._drop_cached_cookies()
    assert a._load_cached_cookies() is False
    assert scraper_factory("B", "pw")._load_cached_cookies() is True


def test_session_cookie_round_trip():
    class FakeResponse:
        def __init__(self):
            self.kwargs = {}

        def set_cookie(self, **kwargs):
            self.kwargs = kwargs

    response = FakeResponse()
    web.set_session(response, "B11234567", "s3cret")

    assert response.kwargs["httponly"] is True
    assert response.kwargs["samesite"] == "strict"
    assert "s3cret" not in response.kwargs["value"]

    class FakeRequest:
        cookies = {web.SESSION_COOKIE: response.kwargs["value"]}

    assert web.get_credentials(FakeRequest()) == ("B11234567", "s3cret")


def test_tampered_session_cookie_is_rejected():
    class FakeRequest:
        cookies = {web.SESSION_COOKIE: "not-a-valid-token"}

    assert web.get_credentials(FakeRequest()) is None


def test_rate_limiter_blocks_after_limit():
    limiter = web.RateLimiter(limit=2, window=300)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    assert limiter.allow("other") is True


def test_rate_limiter_refund_returns_budget():
    limiter = web.RateLimiter(limit=1, window=300)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    limiter.refund("k")
    assert limiter.allow("k") is True


def test_restored_cookies_are_pinned_to_the_portal_host(scraper_factory):
    """Regression: unscoped cookies were sent to every host, including over HTTP."""
    s = scraper_factory("B11234567", "pw")
    s.client.cookies.set("StuScoreQueryServ", "session-value")
    s._store_cookies()

    fresh = scraper_factory("B11234567", "pw")
    assert fresh._load_cached_cookies() is True
    portal = fresh.client.build_request("GET", f"https://{NtustGradeScraper.PORTAL_HOST}/x")
    elsewhere = fresh.client.build_request("GET", "http://evil.example.com/x")
    assert "StuScoreQueryServ" in (portal.headers.get("cookie") or "")
    assert elsewhere.headers.get("cookie") is None


def test_student_info_cache_is_not_a_plaintext_roster(scraper_factory):
    s = scraper_factory("B11234567", "pw")
    assert s._info_key != s.username
    assert len(s._info_key) == 64


def test_cache_dir_is_read_at_call_time(tmp_path, monkeypatch):
    """Regression: CACHE_DIR must apply even though the module imports before .env loads."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    assert gpa.cache_path("cookie_cache.json") == tmp_path / "cookie_cache.json"


def test_cache_file_is_owner_only(scraper_factory):
    s = scraper_factory("B11234567", "pw")
    s.client.cookies.set("StuScoreQueryServ", "v")
    s._store_cookies()
    assert stat.S_IMODE(s._cookie_cache_file.stat().st_mode) == 0o600


def test_expired_entries_are_pruned_on_write(scraper_factory, monkeypatch):
    stale = scraper_factory("old-user", "pw")
    stale.client.cookies.set("StuScoreQueryServ", "v")
    stale._store_cookies()

    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time + 2 * gpa.COOKIE_CACHE_TTL)

    fresh = scraper_factory("new-user", "pw")
    fresh.client.cookies.set("StuScoreQueryServ", "v")
    fresh._store_cookies()

    with open(fresh._cookie_cache_file, encoding="utf-8") as f:
        assert len(json.load(f)) == 1


def test_rate_limiter_prunes_at_most_once_per_window():
    """Regression: pruning ran on every call, making each request O(number of keys)."""
    limiter = web.RateLimiter(limit=5, window=300)
    for i in range(2000):
        limiter.allow(f"key-{i}")

    scans = 0
    original = limiter._maybe_prune

    def counting(now):
        nonlocal scans
        before = limiter._next_prune
        original(now)
        if limiter._next_prune != before:
            scans += 1

    limiter._maybe_prune = counting
    for i in range(2000):
        limiter.allow(f"more-{i}")
    assert scans == 0


def test_cache_writes_survive_a_concurrent_process(tmp_path, monkeypatch):
    """The in-process lock does not cross processes; flock must."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    script = textwrap.dedent(f"""
        import os, sys
        os.environ["CACHE_DIR"] = {str(tmp_path)!r}
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "k")
        sys.path.insert(0, {str(gpa.ROOT)!r})
        from gpa_analyzer.analyzer import NtustGradeScraper
        for i in range(20):
            s = NtustGradeScraper(f"{{sys.argv[1]}}-{{i}}", "pw")
            s.client.cookies.set("StuScoreQueryServ", "v")
            s._store_cookies()
            s.close()
    """)
    path = tmp_path / "worker.py"
    path.write_text(script, encoding="utf-8")

    procs = [
        subprocess.Popen([sys.executable, str(path), tag], env={**os.environ})
        for tag in ("alpha", "beta")
    ]
    for p in procs:
        assert p.wait(timeout=60) == 0

    with open(tmp_path / "cookie_cache.json", encoding="utf-8") as f:
        assert len(json.load(f)) == 40
