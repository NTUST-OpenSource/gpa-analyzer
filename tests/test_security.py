import json
import stat
import time

import pytest

import app as web
import GpaAnalyzer as gpa
from GpaAnalyzer import NtustGradeScraper


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


def test_rate_limiter_check_does_not_consume_budget():
    limiter = web.RateLimiter(limit=1, window=300)
    assert limiter.check("k") is True
    assert limiter.check("k") is True
    limiter.record("k")
    assert limiter.check("k") is False


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
