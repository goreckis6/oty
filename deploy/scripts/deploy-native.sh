#!/usr/bin/env bash
# Deploy bez Dockera: Python jak start.sh + Caddy na hoście + systemd.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-yts.cool}"
ACME_EMAIL="${ACME_EMAIL:-}"
APP_PORT="${APP_PORT:-8080}"

cd "$APP_DIR"
export DEBIAN_FRONTEND=noninteractive

install_deps() {
  echo "==> Pakiety (Python, ffmpeg, Caddy)..."
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip ffmpeg curl caddy rsync
  systemctl enable caddy
}

setup_firewall() {
  if ! command -v ufw >/dev/null; then
    return 0
  fi
  echo "==> Firewall (80, 443, SSH)..."
  ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
}

setup_env() {
  mkdir -p /etc/ytdown "$APP_DIR/downloads" "$APP_DIR/secrets"
  if [[ ! -f /etc/ytdown/env ]]; then
    cp "$APP_DIR/deploy/env.example" /etc/ytdown/env
  fi
  # Produkcja: app tylko lokalnie, Caddy na zewnątrz
  grep -q '^YTDOWN_HOST=' /etc/ytdown/env && sed -i 's/^YTDOWN_HOST=.*/YTDOWN_HOST=127.0.0.1/' /etc/ytdown/env || echo "YTDOWN_HOST=127.0.0.1" >> /etc/ytdown/env
  grep -q '^YTDOWN_PORT=' /etc/ytdown/env && sed -i "s/^YTDOWN_PORT=.*/YTDOWN_PORT=${APP_PORT}/" /etc/ytdown/env || echo "YTDOWN_PORT=${APP_PORT}" >> /etc/ytdown/env
  grep -q '^YTDOWN_DOWNLOADS_DIR=' /etc/ytdown/env || echo "YTDOWN_DOWNLOADS_DIR=${APP_DIR}/downloads" >> /etc/ytdown/env
  if [[ -f "$APP_DIR/secrets/cookies.txt" ]]; then
    grep -q '^YTDOWN_COOKIES_FILE=' /etc/ytdown/env && sed -i "s|^YTDOWN_COOKIES_FILE=.*|YTDOWN_COOKIES_FILE=${APP_DIR}/secrets/cookies.txt|" /etc/ytdown/env || echo "YTDOWN_COOKIES_FILE=${APP_DIR}/secrets/cookies.txt" >> /etc/ytdown/env
  fi
}

setup_caddy() {
  local caddyfile="/etc/caddy/Caddyfile"
  if [[ -n "$ACME_EMAIL" ]]; then
    cat > "$caddyfile" <<EOF
{
	email ${ACME_EMAIL}
}

${DOMAIN} {
	reverse_proxy 127.0.0.1:${APP_PORT}
}
EOF
  else
    cat > "$caddyfile" <<EOF
${DOMAIN} {
	reverse_proxy 127.0.0.1:${APP_PORT}
}
EOF
  fi
  systemctl restart caddy
}

setup_systemd() {
  cat > /etc/systemd/system/ytdown.service <<EOF
[Unit]
Description=YTDown YouTube downloader
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/ytdown/env
ExecStart=${APP_DIR}/scripts/run.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  chmod +x "${APP_DIR}/scripts/run.sh"
  systemctl daemon-reload
  systemctl enable ytdown
}

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && [[ -f docker-compose.yml ]]; then
  echo "==> Zatrzymuję stare kontenery Docker..."
  docker compose down 2>/dev/null || true
fi

install_deps
setup_firewall
setup_env
setup_caddy
setup_systemd

echo "==> Instalacja zależności Python..."
if [[ ! -d "${APP_DIR}/.venv" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install -q --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/backend/requirements.txt"
systemctl restart ytdown
sleep 2

echo "==> Czekam na health..."
for i in $(seq 1 30); do
  app_ok=0
  caddy_ok=0
  curl -sf "http://127.0.0.1:${APP_PORT}/api/health" >/dev/null && app_ok=1
  curl -sf "http://127.0.0.1/api/health" -H "Host: ${DOMAIN}" >/dev/null && caddy_ok=1
  if [[ "$app_ok" = 1 && "$caddy_ok" = 1 ]]; then
    curl -s "http://127.0.0.1:${APP_PORT}/api/health"
    echo ""
    echo "==> Deploy native OK — https://${DOMAIN}"
    systemctl is-active ytdown caddy
    exit 0
  fi
  sleep 5
done

echo "==> Health timeout"
systemctl status ytdown --no-pager || true
systemctl status caddy --no-pager || true
journalctl -u ytdown -n 30 --no-pager || true
exit 1
