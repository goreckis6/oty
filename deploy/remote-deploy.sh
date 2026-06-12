#!/usr/bin/env bash
# Runs on the server after each deploy (GitHub Actions or manual).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
APP_USER="${APP_USER:-ytdown}"
VENV="$APP_DIR/.venv"

echo "==> Deploying YTDown to $APP_DIR"

if [[ "$(id -u)" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg not found. Run: sudo apt install ffmpeg"
  exit 1
fi

$SUDO mkdir -p "$APP_DIR"
$SUDO chown -R "$APP_USER:$APP_USER" "$APP_DIR"

run_as_app() {
  if [[ "$(id -un)" == "$APP_USER" ]]; then
    bash -c "$1"
  else
    $SUDO -u "$APP_USER" bash -c "$1"
  fi
}

run_as_app "cd '$APP_DIR' && \
  if [[ ! -d '$VENV' ]]; then python3 -m venv '$VENV'; fi && \
  '$VENV/bin/pip' install --upgrade pip && \
  '$VENV/bin/pip' install -r backend/requirements.txt"

chmod +x "$APP_DIR/scripts/run.sh" "$APP_DIR/deploy/remote-deploy.sh" 2>/dev/null || true
$SUDO chmod +x "$APP_DIR/scripts/run.sh" "$APP_DIR/deploy/remote-deploy.sh" 2>/dev/null || true

echo "==> ffmpeg: $(ffmpeg -version | head -1)"

if $SUDO systemctl is-enabled ytdown >/dev/null 2>&1; then
  $SUDO systemctl restart ytdown
  sleep 2
  $SUDO systemctl is-active ytdown
  PORT=$(grep -E '^YTDOWN_PORT=' /etc/ytdown/env 2>/dev/null | cut -d= -f2 || echo 8082)
  curl -sf "http://127.0.0.1:${PORT}/api/health" && echo ""
  echo "==> Deploy OK"
else
  echo "==> Files updated. Enable service: sudo systemctl enable --now ytdown"
fi
