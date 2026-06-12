#!/usr/bin/env bash
# Jednorazowy setup VPS: Docker + nginx + firewall.
# Uruchom na serwerze jako root: bash deploy/vps-setup.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"

apt-get update
apt-get install -y docker.io docker-compose-v2 nginx curl

mkdir -p "$APP_DIR/downloads"
cp "$APP_DIR/deploy/nginx/ytdown.conf" /etc/nginx/sites-available/ytdown
ln -sf /etc/nginx/sites-available/ytdown /etc/nginx/sites-enabled/ytdown
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl enable --now nginx

# Cron: sprzątanie starych plików co godzinę
CRON_LINE="0 * * * * YTDOWN_DOWNLOADS_DIR=$APP_DIR/downloads $APP_DIR/deploy/scripts/cleanup-downloads.sh"
(crontab -l 2>/dev/null | grep -v cleanup-downloads; echo "$CRON_LINE") | crontab -

ufw allow 80/tcp
ufw allow 443/tcp
ufw allow OpenSSH
ufw --force enable

echo "==> Setup OK. Teraz:"
echo "  rsync projektu do $APP_DIR"
echo "  cd $APP_DIR && docker compose up -d --build"
echo "  http://$(curl -sf ifconfig.me || hostname -I | awk '{print $1}')"
