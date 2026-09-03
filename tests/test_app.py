import pytest
from fastapi.testclient import TestClient

import app as web

GRADE_DATA = {
    "courses": [{"semester": "113-1", "course_id": "CS1", "credits": "3", "grade": "A"}],
    "rankings": [],
    "credits_summary": {},
    "student_info": {"student_id": "B11234567", "name": "王小明", "class_name": "資工四A"},
}


@pytest.fixture(autouse=True)
def reset_limiters():
    web.login_limiter = web.RateLimiter(*web.LOGIN_RATE)
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


def test_login_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(web, "_verify_credentials", lambda u, p: False)
    for _ in range(web.LOGIN_RATE[0]):
        client.post("/login", data={"username": "B11234567", "password": "bad"})
    r = client.post("/login", data={"username": "B11234567", "password": "bad"})
    assert r.status_code == 429


def test_login_rejects_cross_origin_post(client):
    r = client.post(
        "/login",
        data={"username": "u", "password": "p"},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


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


def test_api_is_rate_limited(authed_client, monkeypatch):
    monkeypatch.setattr(web, "_fetch_grade_data", lambda u, p: dict(GRADE_DATA))
    for _ in range(web.API_RATE[0]):
        authed_client.get("/api/grade-data")
    assert authed_client.get("/api/grade-data").status_code == 429
