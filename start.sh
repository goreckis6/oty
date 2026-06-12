#!/usr/bin/env bash
# Local development launcher
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export YTDOWN_HOST="${YTDOWN_HOST:-127.0.0.1}"
export YTDOWN_PORT="${YTDOWN_PORT:-3000}"
export WORKER_ID="${WORKER_ID:-w1}"
export YTDOWN_DOWNLOADS_DIR="${YTDOWN_DOWNLOADS_DIR:-$(pwd)/downloads}"
mkdir -p "$YTDOWN_DOWNLOADS_DIR"

if [[ -d backend/.venv ]]; then
  source backend/.venv/bin/activate
else
  python3 -m venv backend/.venv
  source backend/.venv/bin/activate
  pip install -q -r backend/requirements.txt
fi

export PATH="$(pwd)/bin:$PATH"
cd backend
exec python -m uvicorn main:app --host "$YTDOWN_HOST" --port "$YTDOWN_PORT" --reload
