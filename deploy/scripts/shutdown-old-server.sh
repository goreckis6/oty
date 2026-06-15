#!/usr/bin/env bash
# Gracefully stop the site on the OLD VPS after DNS points to the new server.
# Run on the OLD server as root (or with sudo). Does NOT delete data.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
UNIT_NAME="ytdown.service"

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "FATAL: run as root or install sudo" >&2
    exit 1
  fi
}

echo "==> Shutting down ytdown on OLD server (data preserved)"
echo "    APP_DIR=${APP_DIR}"

if run_root systemctl is-enabled "$UNIT_NAME" >/dev/null 2>&1; then
  echo "==> Disabling ${UNIT_NAME}..."
  run_root systemctl disable "$UNIT_NAME" || true
  run_root systemctl stop "$UNIT_NAME" || true
fi

if [ -d "$APP_DIR" ] && command -v docker >/dev/null 2>&1; then
  echo "==> Stopping Docker containers..."
  cd "$APP_DIR"
  docker compose down 2>/dev/null || true
  docker rm -f site-api site-caddy ytdown ytdown-caddy 2>/dev/null || true
fi

echo ""
echo "==> Old server stopped"
echo "    Data kept at: ${APP_DIR}/backend/data/movies.db"
echo "    You can keep the VPS off or wipe it after confirming the new server works."
