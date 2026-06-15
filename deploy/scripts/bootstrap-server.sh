#!/usr/bin/env bash
# Prepare a fresh VPS for ytdown deploy (Docker, dirs, firewall).
# Run on the NEW server as root (or with sudo).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DEPLOY_USER="${DEPLOY_USER:-root}"

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

echo "==> Bootstrap VPS for ytdown"
echo "    APP_DIR=${APP_DIR}"

if ! command -v curl >/dev/null 2>&1 || ! command -v rsync >/dev/null 2>&1; then
  echo "==> Installing curl, rsync..."
  run_root apt-get update -qq
  run_root apt-get install -y curl ca-certificates rsync
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker..."
  curl -fsSL https://get.docker.com | run_root sh
else
  echo "==> Docker already installed: $(docker --version)"
fi

run_root systemctl enable docker.service
run_root systemctl start docker.service

echo "==> Creating app directories..."
run_root mkdir -p \
  "${APP_DIR}/backend/data" \
  "${APP_DIR}/public/js" \
  "${APP_DIR}/public/css" \
  "${APP_DIR}/public/uploads" \
  "${APP_DIR}/public/downloads" \
  "${APP_DIR}/public/.well-known" \
  "${APP_DIR}/deploy/caddy"
run_root chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

if command -v ufw >/dev/null 2>&1; then
  echo "==> Opening firewall ports 22, 80, 443 (ufw)..."
  run_root ufw allow OpenSSH || true
  run_root ufw allow 80/tcp || true
  run_root ufw allow 443/tcp || true
  if run_root ufw status | grep -q "Status: active"; then
    echo "    ufw already active — rules added"
  else
    echo "    ufw inactive — enable manually if needed: ufw enable"
  fi
fi

echo ""
echo "==> Bootstrap OK"
echo ""
echo "Next steps:"
echo "  1. Add GitHub Actions SSH public key to ${DEPLOY_USER}@this-server:~/.ssh/authorized_keys"
echo "  2. Copy site data from old server:"
echo "       bash deploy/scripts/migrate-data.sh OLD_HOST NEW_HOST"
echo "  3. Update GitHub Secrets: DEPLOY_HOST → IP this server"
echo "  4. Run GitHub Actions → Deploy (workflow_dispatch) or git push main"
echo "  5. Test: curl -sk --resolve 'DOMAIN:443:NEW_IP' https://DOMAIN/api/v1/health"
echo "  6. Point DNS A record to NEW_IP, then shut down old server"
