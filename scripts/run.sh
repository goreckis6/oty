#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$APP_DIR/.venv"

if [[ -f /etc/ytdown/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/ytdown/env
  set +a
fi

export YTDOWN_HOST="${YTDOWN_HOST:-0.0.0.0}"
export YTDOWN_PORT="${YTDOWN_PORT:-8082}"

if [[ -d "$APP_DIR/bin" ]]; then
  export PATH="$APP_DIR/bin:$PATH"
fi

cd "$APP_DIR/backend"
exec "$VENV/bin/python" -m uvicorn main:app \
  --host "$YTDOWN_HOST" \
  --port "$YTDOWN_PORT" \
  --workers 1
