import hashlib
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from GpaAnalyzer import NtustGradeScraper, analyze_courses

load_dotenv()

logger = logging.getLogger("gpa_analyzer")

ROOT = Path(__file__).resolve().parent
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() not in {"0", "false", "no"}
SESSION_COOKIE = "__Host-gpaa_session" if COOKIE_SECURE else "gpaa_session"
SESSION_MAX_AGE = 7 * 24 * 60 * 60

LOGIN_RATE = (5, 300)
API_RATE = (30, 300)

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


class _EndpointFilter(logging.Filter):
    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def filter(self, record: logging.LogRecord) -> bool:
        return self._path not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_EndpointFilter("/healthz"))


def _build_fernet() -> Fernet:
    secret = os.getenv("SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(secret)
    except (ValueError, TypeError) as e:
        raise RuntimeError("SECRET_KEY is not a valid Fernet key.") from e


FERNET = _build_fernet()

app = FastAPI(title="GPA Analyzer", docs_url=None, redoc_url=None, openapi_url=None)
templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


class RateLimiter:
    def __init__(self, limit: int, window: int):
        self._limit = limit
        self._window = window
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:
                self._prune(now)
            hits = self._hits[key]
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self._window]:
            del self._hits[key]


login_limiter = RateLimiter(*LOGIN_RATE)
api_limiter = RateLimiter(*API_RATE)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_same_origin(request: Request) -> None:
    """Rejects cross-site form posts; SameSite cookies alone do not cover login CSRF."""
    origin = request.headers.get("origin")
    source = origin or request.headers.get("referer")
    if not source:
        return
    host = urlsplit(source).netloc
    if host and host != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected.")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    if COOKIE_SECURE:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


def set_session(response: Response, username: str, password: str) -> None:
    token = FERNET.encrypt(json.dumps({"u": username, "p": password}).encode("utf-8"))
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token.decode("utf-8"),
        httponly=True,
        samesite="strict",
        secure=COOKIE_SECURE,
        max_age=SESSION_MAX_AGE,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=COOKIE_SECURE
    )


def get_credentials(request: Request) -> tuple[str, str] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        raw = FERNET.decrypt(token.encode("utf-8"), ttl=SESSION_MAX_AGE)
        cred = json.loads(raw.decode("utf-8"))
        username, password = cred["u"], cred["p"]
    except InvalidToken, ValueError, TypeError, KeyError, json.JSONDecodeError:
        return None
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    return username, password


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not get_credentials(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "index.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    _require_same_origin(request)

    user_key = hashlib.sha256(username.encode("utf-8")).hexdigest()
    if not login_limiter.allow(_client_key(request)) or not login_limiter.allow(user_key):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Too many login attempts. Please wait a few minutes."},
            status_code=429,
        )

    try:
        authenticated = await run_in_threadpool(_verify_credentials, username, password)
    except Exception:
        logger.exception("Login failed for an unexpected reason")
        return templates.TemplateResponse(
            request, "login.html", {"error": "Service temporarily unavailable."}, status_code=502
        )

    if not authenticated:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Login failed, please check your credentials."},
            status_code=401,
        )

    response = RedirectResponse(url="/", status_code=302)
    set_session(response, username, password)
    return response


@app.post("/logout")
async def logout(request: Request):
    _require_same_origin(request)
    response = RedirectResponse(url="/login", status_code=302)
    clear_session(response)
    return response


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def _verify_credentials(username: str, password: str) -> bool:
    with NtustGradeScraper(username, password) as scraper:
        return scraper.login()


def _fetch_grade_data(username: str, password: str) -> dict:
    with NtustGradeScraper(username, password) as scraper:
        if not scraper.login():
            raise HTTPException(
                status_code=401, detail="Authentication failed. Please log in again."
            )

        grade_data = scraper.fetch_grades()
        if grade_data.get("error") or not grade_data.get("courses"):
            logger.warning("Grade fetch unsuccessful: %s", grade_data.get("error", "no_courses"))
            raise HTTPException(
                status_code=502, detail="Could not retrieve grades from the school system."
            )
        return grade_data


@app.get("/api/grade-data")
async def api_grade_data(request: Request):
    credentials = get_credentials(request)
    if not credentials:
        raise HTTPException(status_code=401, detail="Not logged in or session expired.")

    if not api_limiter.allow(_client_key(request)):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a few minutes.")

    try:
        grade_data = await run_in_threadpool(_fetch_grade_data, *credentials)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while fetching grade data")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from None

    analysis = analyze_courses(grade_data.get("courses", []))
    return JSONResponse(
        content={
            **grade_data,
            "analysis": analysis,
            "semesters": [p["semester"] for p in analysis.get("per_semester", [])],
        }
    )
