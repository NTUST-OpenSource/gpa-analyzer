<div align="center">

# GPA Analyzer

[![License](https://img.shields.io/github/license/NTUST-OpenSource/gpa-analyzer?style=for-the-badge)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/NTUST-OpenSource/gpa-analyzer/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/NTUST-OpenSource/gpa-analyzer/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![GHCR](https://img.shields.io/badge/GHCR-Image-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://github.com/NTUST-OpenSource/gpa-analyzer/pkgs/container/gpa-analyzer)

[繁體中文](README.md) | **English**

</div>

## Overview

GPA Analyzer is a **self-hosted** transcript analyser for NTUST students.

The university's grade portal hands you a single table — no GPA, no trends, no grade distribution. This project signs in with your account, pulls your full transcript, and turns it into something you can actually read.

### 📊 **Grade analysis**
- Per-semester and overall **GPA**, credit-weighted, with A+ = 4.3
- Attempted, earned, and in-progress credits at a glance
- Pass/withdrawn/waived courses are automatically excluded from GPA

### 📈 **Interactive charts**
- GPA trend line across semesters
- Credits taken per semester
- Stacked breakdown of credits by letter grade

### 🏅 **Rankings and courses**
- Class and department rank, per semester and cumulative
- Full course list with course ID, credits, grade, and general-education dimension
- Layouts for phone, tablet, and desktop

<br/>

## Quick start

### Docker (recommended)

```bash
# Generate a session encryption key
SECRET_KEY=$(docker run --rm ghcr.io/ntust-opensource/gpa-analyzer:latest \
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

docker run -d --name gpa-analyzer \
  -p 8000:8000 \
  -e SECRET_KEY="$SECRET_KEY" \
  -v gpa-analyzer-cache:/data \
  ghcr.io/ntust-opensource/gpa-analyzer:latest
```

Images are published for `linux/amd64` and `linux/arm64`.

> [!IMPORTANT]
> `COOKIE_SECURE` defaults to `true`, so session cookies are only sent over HTTPS.
> To test locally over `http://`, add `-e COOKIE_SECURE=false`. In production, run behind an HTTPS reverse proxy.

### Docker Compose

```yaml
services:
  gpa-analyzer:
    image: ghcr.io/ntust-opensource/gpa-analyzer:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY in .env}
      FORWARDED_ALLOW_IPS: 127.0.0.1
    volumes:
      - cache:/data

volumes:
  cache:
```

### From source

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
git clone https://github.com/NTUST-OpenSource/gpa-analyzer.git
cd gpa-analyzer

cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Put the output in SECRET_KEY, and set COOKIE_SECURE=false for local HTTP testing

uv sync
./start.sh
```

Open <http://localhost:20001> and sign in with your student ID and Moodle password.

<br/>

## Configuration

Everything is configured through environment variables, which may live in `.env` (see [`.env.example`](.env.example)).

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | none, **required** | Fernet key used to encrypt session cookies. The service refuses to start without it |
| `COOKIE_SECURE` | `true` | Restrict session cookies to HTTPS. When true, the cookie also gets the `__Host-` prefix |
| `PORT` | `8000` (`20001` via `start.sh`) | Listening port |
| `CACHE_DIR` | `.cache` (`/data` in the container) | Where the scraper stores its caches |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Which peers may set `X-Forwarded-For`. **Set this to your actual reverse proxy** |
| `TRUSTED_ORIGINS` | empty | Extra hostnames accepted in `Origin`, comma separated. Only needed when a proxy rewrites `Host` |
| `LOGIN_FAILURE_LIMIT` | `5` | Failed sign-ins allowed per account and per IP, per 5 minutes |
| `LOGIN_ATTEMPT_LIMIT` | `120` | Sign-in attempts allowed per IP, per 5 minutes. Raise it when many students share one NAT address |
| `API_RATE_LIMIT` | `30` | API requests allowed per IP, per 5 minutes |
| `NTUST_USERNAME` / `NTUST_PASSWORD` | none | Used only by the `GpaAnalyzer.py` CLI. The web service never reads them |

> [!NOTE]
> Only failed sign-ins count against `LOGIN_FAILURE_LIMIT`, so ordinary users are never locked out by signing in.
> If your reverse proxy does not preserve the original `Host` header, every sign-in is rejected with 403 — set `TRUSTED_ORIGINS` in that case.

> [!WARNING]
> Leaking `SECRET_KEY` is equivalent to leaking every user's password. Keep it out of version control.
> Rotating `SECRET_KEY` invalidates all existing sessions and forces users to sign in again.

### Command line

Print the analysis as JSON without starting the web service:

```bash
uv run python GpaAnalyzer.py <student-id> <password>
# or set NTUST_USERNAME / NTUST_PASSWORD in .env and run it bare
uv run python GpaAnalyzer.py
```

<br/>

## Security

This service handles university credentials. Here is how it treats them:

| Area | Approach |
|---|---|
| **Credential storage** | Encrypted with Fernet (AES-128-CBC + HMAC) into a browser cookie; there is no server-side database. The cookie is `HttpOnly` + `SameSite=Strict` and expires after 7 days |
| **Why the password is kept** | The grade portal offers no API and no long-lived token, so every query needs a fresh sign-in — the password has to be recoverable |
| **TLS** | Connections to the university verify the full chain, expiry, and hostname. Only the strict RFC 5280 extension checks added in Python 3.13+ are relaxed, because an intermediate in the NTUST chain omits its Subject Key Identifier |
| **Cookie cache** | Portal session cookies are cached for 30 minutes under `HMAC(SECRET_KEY, user:password)`, so a different password never hits the cache and a cache hit can never substitute for authentication |
| **Brute force** | Failed sign-ins are capped at 5 per 5 minutes per IP and per account (successes are not counted); sign-in attempts at 120 per IP; the API at 30 requests per 5 minutes |
| **XSS** | Strict CSP (`default-src 'none'`, no `unsafe-inline`), all front-end assets served locally with no CDN, and every value injected into the DOM is escaped |
| **CSRF** | `SameSite=Strict` cookies, Origin checks on sign-in and sign-out, and sign-out accepts POST only |

> [!CAUTION]
> This is self-hosted software. Whoever operates an instance is technically able to read its users' passwords — only use an instance you trust.

Please report security issues through a [GitHub Security Advisory](https://github.com/NTUST-OpenSource/gpa-analyzer/security/advisories/new) rather than a public issue.

<br/>

## Development

```bash
uv sync --all-groups

uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
```

Styles are generated by Tailwind CSS. After changing classes in `templates/` or `static/app.js`, rebuild:

```bash
npm install
npm run build              # writes static/vendor/tailwind.css
```

CI fails if `static/vendor/tailwind.css` is out of date, so don't skip the rebuild.

### Project layout

```
app.py               FastAPI application: sign-in, sessions, API endpoints
GpaAnalyzer.py       Scraper, HTML parsing, and GPA computation
templates/           Jinja2 templates
static/              Front-end assets (app.js and self-hosted vendor/)
assets/tailwind.css  Tailwind source stylesheet
tests/               pytest suite
```

<br/>

## License

Licensed under the **GNU Affero General Public License v3.0 or later**. See [LICENSE](LICENSE) for the full text.

The key AGPL obligation: if you modify this project and offer it to others over a network, you must offer those users your modified source code.

<br/>

## Disclaimer

This project is not officially affiliated with National Taiwan University of Science and Technology. Users are responsible for complying with their institution's acceptable-use policies.
