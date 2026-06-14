#!/usr/bin/env bash
# Install systemd unit so the site starts automatically after VPS reboot.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
UNIT_NAME="ytdown.service"
UNIT_SRC="${APP_DIR}/deploy/systemd/ytdown.service"
UNIT_DEST="/etc/systemd/system/${UNIT_NAME}"

if [ ! -f "$UNIT_SRC" ]; then
  echo "FATAL: missing ${UNIT_SRC}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "FATAL: docker not installed" >&2
  exit 1
fi

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "FATAL: root or sudo required to install ${UNIT_NAME}" >&2
    exit 1
  fi
}

echo "==> Enabling Docker on boot..."
run_root systemctl enable docker.service

echo "==> Installing ${UNIT_NAME}..."
sed "s|@APP_DIR@|${APP_DIR}|g" "$UNIT_SRC" | run_root tee "$UNIT_DEST" >/dev/null
run_root chmod 644 "$UNIT_DEST"
run_root systemctl daemon-reload
run_root systemctl enable "$UNIT_NAME"
run_root systemctl restart "$UNIT_NAME"

echo "==> Boot service active:"
run_root systemctl --no-pager status "$UNIT_NAME" || true
