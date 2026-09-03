#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

: "${PORT:=20001}"
: "${HOST:=0.0.0.0}"
# Trust forwarded headers only from the reverse proxy in front of this app.
: "${FORWARDED_ALLOW_IPS:=127.0.0.1}"

exec uv run uvicorn app:app \
    --host "$HOST" \
    --port "$PORT" \
    --proxy-headers \
    --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
