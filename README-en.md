<div align="center">
<a href="https://gpa.ntust.org">
  <img width="2000" src=".github/assets/banner.png" alt="GPA Analyzer Banner"/>
</a>
<br>

[![License](https://img.shields.io/github/license/NTUST-OpenSource/gpa-analyzer?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

[繁體中文](README.md) | **English**

</div>

## Overview

GPA Analyzer is a self-hosted grade visualisation and analysis tool

Credentials are encrypted and stored in the user's browser; the server keeps no credentials

### **Grade computation**
- Per-semester / overall **GPA**
- Attempted, earned, and in-progress credits
- Second withdrawals / waived courses

### **Interactive charts**
- Per-semester GPA line chart
- Stacked credits per letter grade, for the grade distribution

### **Rankings and courses**
- Class, department, and cumulative rankings
- Full course list with course ID, credits, grade, and general-education dimension, filterable by semester
- Adapts to the window size

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
> To test over unencrypted `http://`, add `-e COOKIE_SECURE=false`

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
      # Address of the reverse proxy in front of this service, so client IPs are
      # read from X-Forwarded-For. Leave unset if nothing proxies to it.
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:-127.0.0.1}
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
uv run python -m gpa_analyzer.app
```

Open <http://localhost:8000> and sign in with your student ID and Moodle password.

<br/>

## Configuration

Everything is configured through environment variables, which may live in `.env` (see [`.env.example`](.env.example))

Values are read with **shell environment > `.env`** precedence: anything already exported in the shell is never overwritten by `.env`

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | none, **required** | Fernet key used to encrypt session cookies. The service refuses to start without it |
| `COOKIE_SECURE` | `true` | Restrict session cookies to HTTPS. When true, the cookie also gets the `__Host-` prefix |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Listening address and port |
| `CACHE_DIR` | `.cache` (`/data` in the container) | Where the scraper stores its caches |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Which peers may set `X-Forwarded-For`. **Set this to your actual reverse proxy** |
| `TRUSTED_ORIGINS` | empty | Extra hostnames accepted in `Origin`, comma separated. Only needed when a proxy rewrites `Host` |
| `LOGIN_FAILURE_LIMIT` | `5` | Failed sign-ins allowed per account, per 5 minutes |
| `LOGIN_ATTEMPT_LIMIT` | `10` | Sign-in attempts allowed per IP, per 5 minutes |
| `API_RATE_LIMIT` | `10` | API requests allowed per account, per 5 minutes |
| `NTUST_USERNAME` / `NTUST_PASSWORD` | none | Used only by the command line mode. The web service never reads them |

> [!NOTE]
> If sign-ins are rejected with 403, the reverse proxy is probably not preserving the original `Host` header — set `TRUSTED_ORIGINS`

### Command line

Print the analysis as JSON without starting the web service:

```bash
uv run python -m gpa_analyzer.analyzer <student-id> <password>

# or set NTUST_USERNAME / NTUST_PASSWORD in .env
uv run python -m gpa_analyzer.analyzer
```

<br/>

## Security

This service handles university credentials. Here is how it treats them:

| Area | Approach |
|---|---|
| **Credential storage** | Encrypted with Fernet (AES-128-CBC + HMAC) into a browser cookie; there is no server-side database. The cookie is `HttpOnly` + `SameSite=Strict` and expires after 7 days |
| **Why the password is kept** | The grade portal offers no API and no long-lived token, so every query needs a fresh sign-in — the password has to be recoverable |
| **TLS** | Connections to the university verify the full chain, expiry, and hostname |
| **Cookie cache** | The portal's session cookies are cached under a derived index for 30 minutes |
| **Brute force** | Failed sign-ins capped at 5 per account / 5 minutes; sign-in attempts at 10 per IP / 5 minutes; the API at 10 per account / 5 minutes |
| **XSS** | Strict CSP, no CDN |
| **CSRF** | `SameSite=Strict` cookies, Origin checks on sign-in and sign-out, and sign-out accepts POST only |

> [!CAUTION]
> Please report security issues through a [GitHub Security Advisory](https://github.com/NTUST-OpenSource/gpa-analyzer/security/advisories/new) rather than a public issue

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

CI checks that `static/vendor/tailwind.css` is up to date

### Project layout

```
gpa_analyzer/app.py       FastAPI application: sign-in, sessions, API endpoints
gpa_analyzer/analyzer.py  Scraper, HTML parsing, and GPA computation
templates/                Jinja2 templates
static/                   Front-end assets (app.js and self-hosted vendor/)
assets/tailwind.css       Tailwind source stylesheet
tests/                    pytest suite
```

<br/>

## License

Copyright (C) 2026 NTUST-OpenSource contributors

Licensed under the **GNU Affero General Public License v3.0 or later**. See [LICENSE](LICENSE) for the full text

<br/>

## Disclaimer

This project is not officially affiliated with National Taiwan University of Science and Technology. Users are responsible for complying with their institution's acceptable-use policies
