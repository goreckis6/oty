#!/usr/bin/env bash
# Uruchomienie aplikacji (serwer / produkcja). Dev: ./start.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$APP_DIR/.venv"

if [[ -f "$APP_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$APP_DIR/.env"
  set +a
fi

if [[ -f /etc/ytdown/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/ytdown/env
  set +a
fi

export YTDOWN_HOST="${YTDOWN_HOST:-0.0.0.0}"
export YTDOWN_PORT="${YTDOWN_PORT:-8080}"
export WORKER_ID="${WORKER_ID:-w1}"
export YTDOWN_DOWNLOADS_DIR="${YTDOWN_DOWNLOADS_DIR:-$APP_DIR/downloads}"
mkdir -p "$YTDOWN_DOWNLOADS_DIR"

if [[ -d "$APP_DIR/bin" ]]; then
  export PATH="$APP_DIR/bin:$PATH"
fi

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

cd "$APP_DIR/backend"
UVICORN_ARGS=(--host "$YTDOWN_HOST" --port "$YTDOWN_PORT" --workers 1)
if [[ "${YTDOWN_DEV:-}" == "1" ]]; then
  UVICORN_ARGS+=(--reload)
fi

exec "$VENV/bin/python" -m uvicorn main:app "${UVICORN_ARGS[@]}"
