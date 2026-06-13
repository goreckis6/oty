#!/usr/bin/env bash
# Jednorazowy setup na domowym PC (wymaga sudo do ffmpeg).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Instalacja zależności (ffmpeg, python3-venv, tailscale)..."
sudo apt-get update -qq
sudo apt-get install -y ffmpeg python3-venv curl

if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
  echo ""
  echo "==> Zaloguj Tailscale:"
  sudo tailscale up
fi

mkdir -p downloads .local-packages
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r backend/requirements.txt

TS_IP="$(tailscale ip -4 2>/dev/null || true)"
echo ""
echo "==> Tailscale IP tego PC: ${TS_IP:-brak — uruchom: sudo tailscale up}"
echo ""
echo "==> Uruchom backend:"
echo "    ./scripts/start-home.sh"
echo ""
echo "==> Na VPS (SSH):"
echo "    HOME_BACKEND_URL=http://${TS_IP:-100.x.x.x}:8080 DOMAIN=yts.cool bash deploy/scripts/setup-vps-home-proxy.sh"
echo "    docker compose down"
echo "    docker compose -f docker-compose.vps-proxy.yml up -d"
