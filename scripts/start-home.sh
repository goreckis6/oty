#!/usr/bin/env bash
# Backend na domowym PC — ruch do YouTube wychodzi z Twojego IP (nie z VPS).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export YTDOWN_HOST="${YTDOWN_HOST:-0.0.0.0}"
export YTDOWN_PORT="${YTDOWN_PORT:-8080}"
export WORKER_ID="${WORKER_ID:-home}"
export YTDOWN_POT_PROVIDER_URL="${YTDOWN_POT_PROVIDER_URL:-none}"
export YTDOWN_PROXY="${YTDOWN_PROXY:-}"

# Cookies z Chrome — zwykle wystarczy na domowym IP (bez pliku cookies.txt).
export YTDOWN_COOKIES_BROWSER="${YTDOWN_COOKIES_BROWSER:-chrome}"

echo "==> YTDown home worker: http://${YTDOWN_HOST}:${YTDOWN_PORT}"
echo "==> YouTube wychodzi z IP tego komputera (cookies: ${YTDOWN_COOKIES_BROWSER})"
exec ./scripts/run.sh
