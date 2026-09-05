import hashlib
import threading
import time

import pytest
from fastapi.testclient import TestClient

from gpa_analyzer import app as web

GRADE_DATA = {
    "courses": [{"semester": "113-1", "course_id": "CS1", "credits": "3", "grade": "A"}],
    "rankings": [],
    "credits_summary": {},
    "student_info": {"student_id": "B11234567", "name": "王小明", "class_name": "資工四A"},
}


@pytest.fixture(autouse=True)
def reset_limiters():
    web.login_failures = web.RateLimiter(*web.LOGIN_FAILURE_RATE)
    web.login_attempts = web.RateLimiter(*web.LOGIN_ATTEMPT_RATE)
    web.api_limiter = web.RateLimiter(*web.API_RATE)


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


@pytest.fixture
def authed_client(client, monkeypatch):
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    client.post("/login", data={"username": "B11234567", "password": "pw"}, follow_redirects=False)
    return client


def test_index_redirects_when_anonymous(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_security_headers_are_set(client):
    r = client.get("/login")
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "'unsafe-inline'" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_pages_are_never_cached(client):
    assert client.get("/login").headers["cache-control"] == "no-store"


def test_asset_version_is_the_content_hash():
    # The whole scheme rests on this: change the bytes, change the URL.
    digest = hashlib.sha256((web.ROOT / "static" / "app.js").read_bytes()).hexdigest()
    assert web._asset_version("app.js") == digest[:12]


def test_versioned_asset_is_cached_forever(client):
    r = client.get(f"/static/app.js?v={web._asset_version('app.js')}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unversioned_asset_revalidates(client):
    # Favicons and the manifest are linked without a hash, so a year-long cache
    # would strand them; they have to ask every time.
    r = client.get("/static/favicon.ico")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_rendered_pages_link_versioned_assets(client, monkeypatch):
    monkeypatch.setattr(web, "get_credentials", lambda request: ("B11234567", "pw"))
    for path, assets in [
        ("/login", ["vendor/tailwind.css"]),
        ("/", ["vendor/tailwind.css", "vendor/chart.umd.min.js", "app.js"]),
    ]:
        body = client.get(path).text
        for asset in assets:
            assert f"{asset}?v={web._asset_version(asset)}" in body


def test_login_success_sets_session_and_redirects(client, monkeypatch):
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    r = client.post(
        "/login", data={"username": "B11234567", "password": "pw"}, follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert web.SESSION_COOKIE in r.cookies


def test_login_failure_returns_401_without_session(client, monkeypatch):
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: False)
    r = client.post("/login", data={"username": "B11234567", "password": "bad"})
    assert r.status_code == 401
    assert web.SESSION_COOKIE not in r.cookies


def test_login_upstream_failure_returns_502(client, monkeypatch):
    def boom(u, p):
        raise RuntimeError("network down")

    monkeypatch.setattr(web, "_verify_credentials", boom)
    assert client.post("/login", data={"username": "u", "password": "p"}).status_code == 502


def test_repeated_login_failures_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: False)
    for _ in range(web.LOGIN_FAILURE_RATE[0]):
        client.post("/login", data={"username": "B11234567", "password": "bad"})
    r = client.post("/login", data={"username": "B11234567", "password": "bad"})
    assert r.status_code == 429


def test_successful_logins_do_not_consume_the_failure_budget(client, monkeypatch):
    """A shared campus NAT must not lock students out after a handful of sign-ins."""
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    for _ in range(web.LOGIN_FAILURE_RATE[0] + 3):
        r = client.post(
            "/login", data={"username": "B11234567", "password": "pw"}, follow_redirects=False
        )
        assert r.status_code == 302


def test_login_accepts_a_trusted_origin_behind_a_rewriting_proxy(client, monkeypatch):
    monkeypatch.setattr(web, "TRUSTED_ORIGINS", {"gpa.example.edu"})
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    r = client.post(
        "/login",
        data={"username": "B11234567", "password": "pw"},
        headers={"origin": "https://gpa.example.edu"},
        follow_redirects=False,
    )
    assert r.status_code == 302


def test_login_rejects_cross_origin_post(client):
    r = client.post(
        "/login",
        data={"username": "u", "password": "p"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_login_rejects_the_opaque_null_origin(client):
    """`null` is what a sandboxed iframe or a data: URL sends, so it must stay
    rejected. Guards against "fixing" the no-referrer outage by allowing it."""
    r = client.post("/login", data={"username": "u", "password": "p"}, headers={"origin": "null"})
    assert r.status_code == 403


def test_referrer_policy_leaves_the_origin_header_intact(client):
    """The other half of that regression: no-referrer nulls Origin on form posts."""
    assert client.get("/login").headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_login_accepts_an_origin_that_differs_only_by_port(client, monkeypatch):
    """Ports are not a cookie boundary, and a proxied Host header may carry one."""
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    r = client.post(
        "/login",
        data={"username": "B11234567", "password": "pw"},
        headers={"origin": "http://testserver:8443"},
        follow_redirects=False,
    )
    assert r.status_code == 302


def test_login_rejects_an_http_origin_when_cookies_require_https(client, monkeypatch):
    monkeypatch.setattr(web, "COOKIE_SECURE", True)
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    r = client.post(
        "/login",
        data={"username": "B11234567", "password": "pw"},
        headers={"origin": "http://testserver"},
    )
    assert r.status_code == 403


def test_a_rejected_origin_says_what_was_compared(client, caplog):
    """Regression: a bare 403 sent operators hunting through the reverse proxy."""
    with caplog.at_level("WARNING", logger="gpa_analyzer"):
        client.post(
            "/login",
            data={"username": "u", "password": "p"},
            headers={"origin": "https://evil.example"},
        )
    assert "evil.example" in caplog.text
    assert "testserver" in caplog.text


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("gpa.ntust.org", "gpa.ntust.org"),
        ("https://gpa.ntust.org", "gpa.ntust.org"),
        ("  https://GPA.ntust.org:8443 ", "gpa.ntust.org"),
        ("null", ""),
        ("", ""),
        ("http://[oops", ""),
    ],
)
def test_origin_host_normalises_trusted_entries(raw, expected):
    """TRUSTED_ORIGINS is documented as hostnames, but a pasted full origin is likelier."""
    assert web._origin_host(raw) == expected


def test_logout_is_not_reachable_by_get(client):
    assert client.get("/logout", follow_redirects=False).status_code == 405


def test_logout_clears_session(authed_client):
    r = authed_client.post("/logout", follow_redirects=False)
    assert r.status_code == 302
    assert authed_client.get("/", follow_redirects=False).headers["location"] == "/login"


def test_api_requires_authentication(client):
    assert client.get("/api/grade-data").status_code == 401


def test_api_returns_analysis(authed_client, monkeypatch):
    monkeypatch.setattr(web, "_fetch_grade_data", lambda u, p: dict(GRADE_DATA))
    payload = authed_client.get("/api/grade-data").json()

    assert payload["semesters"] == ["113-1"]
    assert payload["analysis"]["overall"]["gpa"] == 4.0
    assert payload["student_info"]["name"] == "王小明"
    assert "html_content" not in payload


def test_api_hides_internal_errors(authed_client, monkeypatch):
    def boom(u, p):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(web, "_fetch_grade_data", boom)
    r = authed_client.get("/api/grade-data")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text


def test_api_returns_empty_analysis_for_a_student_with_no_grades(authed_client, monkeypatch):
    monkeypatch.setattr(
        web,
        "_fetch_grade_data",
        lambda u, p: {"courses": [], "rankings": [], "credits_summary": {}, "student_info": {}},
    )
    r = authed_client.get("/api/grade-data")
    assert r.status_code == 200
    assert r.json()["analysis"]["overall"]["gpa"] is None


def test_authenticated_responses_are_not_cached(authed_client, monkeypatch):
    monkeypatch.setattr(web, "_fetch_grade_data", lambda u, p: dict(GRADE_DATA))
    assert authed_client.get("/api/grade-data").headers["cache-control"] == "no-store"


def test_csp_allows_the_web_manifest(client):
    assert "manifest-src 'self'" in client.get("/login").headers["content-security-policy"]


def test_api_is_rate_limited_per_session(authed_client, monkeypatch):
    monkeypatch.setattr(web, "_fetch_grade_data", lambda u, p: dict(GRADE_DATA))
    for _ in range(web.API_RATE[0]):
        authed_client.get("/api/grade-data")
    assert authed_client.get("/api/grade-data").status_code == 429


def test_concurrent_wrong_passwords_cannot_outrun_the_lockout(client, monkeypatch):
    """Regression: the budget must be consumed before the slow upstream call."""
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: time.sleep(0.3) or False)

    codes: list[int] = []
    lock = threading.Lock()

    def attempt():
        status = client.post(
            "/login", data={"username": "B11234567", "password": "bad"}
        ).status_code
        with lock:
            codes.append(status)

    threads = [threading.Thread(target=attempt) for _ in range(web.LOGIN_FAILURE_RATE[0] + 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert codes.count(401) <= web.LOGIN_FAILURE_RATE[0]
    assert 429 in codes


def test_malformed_origin_is_rejected_not_a_server_error(client):
    """Regression: urlsplit raised ValueError out of the handler, returning 500."""
    r = client.post(
        "/login", data={"username": "u", "password": "p"}, headers={"origin": "http://[oops"}
    )
    assert r.status_code == 403


def test_upstream_outage_does_not_lock_out_the_account(client, monkeypatch):
    """Regression: 502s consumed the failure budget, locking out the right password."""

    def outage(u, p):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(web, "_verify_credentials", outage)
    for _ in range(web.LOGIN_FAILURE_RATE[0] + 2):
        assert (
            client.post("/login", data={"username": "B11234567", "password": "pw"}).status_code
            == 502
        )

    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: True)
    r = client.post(
        "/login", data={"username": "B11234567", "password": "pw"}, follow_redirects=False
    )
    assert r.status_code == 302
