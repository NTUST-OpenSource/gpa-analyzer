import time

import pytest

import app as web
import GpaAnalyzer as gpa
from GpaAnalyzer import NtustGradeScraper


@pytest.fixture
def scraper_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(NtustGradeScraper, "COOKIE_CACHE_FILE", tmp_path / "cookies.json")
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
