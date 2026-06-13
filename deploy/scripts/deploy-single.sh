#!/usr/bin/env bash
# Deploy na jednym VPS (bez load balancera) — Caddy + HTTPS na domenie.
# DEPLOY_MODE=native → Python jak start.sh (bez Dockera)
# DEPLOY_MODE=docker  → docker compose (domyślnie)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-yts.cool}"
ACME_EMAIL="${ACME_EMAIL:-}"
DEPLOY_MODE="${DEPLOY_MODE:-docker}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$DEPLOY_MODE" == "native" ]]; then
  export APP_DIR DOMAIN ACME_EMAIL
  exec bash "${SCRIPT_DIR}/deploy-native.sh"
fi

cd "$APP_DIR"
mkdir -p downloads deploy/caddy

export DEBIAN_FRONTEND=noninteractive

install_docker() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    return 0
  fi
  echo "==> Instalacja Docker..."
  apt-get update -qq
  apt-get install -y -qq docker.io docker-compose-v2 curl
  systemctl enable --now docker
  sleep 3
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

free_web_ports() {
  if ! command -v ss >/dev/null; then
    return 0
  fi
  if ss -tlnH 2>/dev/null | grep -q ':80 '; then
    if ! docker ps --format '{{.Ports}}' 2>/dev/null | grep -q '0.0.0.0:80->'; then
      echo "==> Port 80 zajęty poza Dockerem — zatrzymuję nginx/apache..."
      systemctl stop nginx apache2 2>/dev/null || true
      systemctl disable nginx apache2 2>/dev/null || true
    fi
  fi
}

generate_caddyfile() {
  local out="deploy/caddy/Caddyfile.runtime"
  if [ -n "$ACME_EMAIL" ]; then
    cat > "$out" <<EOF
{
	email ${ACME_EMAIL}
}

${DOMAIN} {
	reverse_proxy ytdown:8080
}
EOF
  else
    cat > "$out" <<EOF
${DOMAIN} {
	reverse_proxy ytdown:8080
}
EOF
  fi
}

setup_cookies_mount() {
  mkdir -p secrets
  if [[ -f secrets/cookies.txt ]]; then
    chmod 644 secrets/cookies.txt
    if ! grep -qE $'[\t](\.youtube\.com|youtube\.com)[\t]' secrets/cookies.txt; then
      echo "==> UWAGA: secrets/cookies.txt nie zawiera cookies youtube.com"
    else
      echo "==> Montuję cookies YouTube ($(grep -cE $'[\t](\.youtube\.com|youtube\.com)[\t]' secrets/cookies.txt || echo 0) wpisów)"
    fi
    cat > docker-compose.override.yml <<'EOF'
services:
  ytdown:
    volumes:
      - ./secrets/cookies.txt:/app/secrets/cookies.txt:ro
EOF
  else
    rm -f docker-compose.override.yml
    echo "==> Brak secrets/cookies.txt — YouTube może blokować VPS bez cookies"
  fi
}

stop_native_stack() {
  echo "==> Zatrzymuję native stack (porty 8080/80/443)..."
  systemctl stop ytdown 2>/dev/null || true
  systemctl disable ytdown 2>/dev/null || true
  systemctl stop caddy 2>/dev/null || true
}

install_docker
setup_firewall
free_web_ports
stop_native_stack
generate_caddyfile
setup_cookies_mount

export DOMAIN ACME_EMAIL

echo "==> Docker build & start (może potrwać 2–5 min przy pierwszym razie)..."
if ! docker compose up -d --build --remove-orphans; then
  echo "==> BŁĄD docker compose. Logi:"
  docker compose logs --tail=80 2>/dev/null || true
  exit 1
fi

echo "==> Czekam na health (app + caddy)..."
for i in $(seq 1 30); do
  app_ok=0
  caddy_ok=0
  curl -sf "http://127.0.0.1:8080/api/health" >/dev/null && app_ok=1
  curl -sf "http://127.0.0.1/api/health" -H "Host: ${DOMAIN}" >/dev/null && caddy_ok=1

  if [ "$app_ok" = 1 ] && [ "$caddy_ok" = 1 ]; then
    curl -s "http://127.0.0.1:8080/api/health"
    echo ""
    echo "==> Deploy na serwerze OK — https://${DOMAIN}"
    docker compose ps
    exit 0
  fi

  if [ "$i" = 5 ] || [ "$i" = 15 ]; then
    echo "==> Status (próba $i/30): app=$app_ok caddy=$caddy_ok"
    docker compose ps || true
    docker compose logs caddy --tail=15 2>/dev/null || true
  fi
  sleep 5
done

echo "==> Health timeout. Kontenery:"
docker compose ps
echo "==> Logi ytdown:"
docker compose logs ytdown --tail=30 2>/dev/null || true
echo "==> Logi caddy:"
docker compose logs caddy --tail=30 2>/dev/null || true
echo "==> Porty:"
ss -tlnp 2>/dev/null | grep -E ':80|:443|:8080' || true
exit 1
