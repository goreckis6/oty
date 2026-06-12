#!/usr/bin/env bash
# Najszybszy deploy na świeży VPS (Ubuntu). Uruchom NA SERWERZE jako root:
#   curl -fsSL https://raw.githubusercontent.com/OWNER/ytdown/main/deploy/vps-quick.sh | bash
# lub po skopiowaniu repo:
#   sudo bash deploy/vps-quick.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
PORT="${YTDOWN_PORT:-8082}"

echo "==> Instalacja Docker"
apt-get update
apt-get install -y docker.io docker-compose-v2 git curl
systemctl enable --now docker

echo "==> Katalog aplikacji: $APP_DIR"
mkdir -p "$APP_DIR"

if [[ ! -f "$APP_DIR/docker-compose.yml" ]]; then
  echo "Skopiuj pliki projektu do $APP_DIR (git clone lub rsync), potem uruchom ponownie."
  echo "  git clone https://github.com/OWNER/ytdown.git $APP_DIR"
  exit 1
fi

cd "$APP_DIR"
export YTDOWN_PORT="$PORT"

echo "==> Build i start"
docker compose up -d --build

echo ""
echo "==> Gotowe!"
echo "    http://$(curl -sf ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):$PORT"
echo "    docker compose -f $APP_DIR/docker-compose.yml logs -f"
