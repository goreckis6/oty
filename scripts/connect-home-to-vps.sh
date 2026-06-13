#!/usr/bin/env bash
# Uruchom NA DOMOWYM PC — utrzymuje SSH reverse tunnel do VPS.
# Wymaga: działający backend (./scripts/start-home.sh) i dostęp SSH do VPS.
set -euo pipefail

VPS_HOST="${VPS_HOST:-167.233.112.233}"
VPS_USER="${VPS_USER:-root}"
LOCAL_PORT="${LOCAL_PORT:-8080}"
REMOTE_PORT="${REMOTE_PORT:-18080}"

echo "==> Tunel: VPS 127.0.0.1:${REMOTE_PORT} → localhost:${LOCAL_PORT}"
echo "==> Po połączeniu, na VPS uruchom:"
echo "    HOME_BACKEND_URL=http://127.0.0.1:${REMOTE_PORT} DOMAIN=yts.cool bash deploy/scripts/setup-vps-home-proxy.sh"
echo "    docker compose -f docker-compose.vps-proxy.yml up -d"
echo ""
echo "==> Naciśnij Ctrl+C aby przerwać tunel."
exec ssh -N \
  -o ServerAliveInterval=30 \
  -o ExitOnForwardFailure=yes \
  -R "127.0.0.1:${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" \
  "${VPS_USER}@${VPS_HOST}"
