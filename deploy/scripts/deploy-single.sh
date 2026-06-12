#!/usr/bin/env bash
# Deploy na jednym VPS (bez load balancera) — Caddy + HTTPS na domenie.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-yts.cool}"
ACME_EMAIL="${ACME_EMAIL:-}"

cd "$APP_DIR"
mkdir -p downloads

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

install_docker
setup_firewall

export DOMAIN ACME_EMAIL

echo "==> Docker build & start (może potrwać 2–5 min przy pierwszym razie)..."
if ! docker compose up -d --build; then
  echo "==> BŁĄD docker compose. Logi:"
  docker compose logs --tail=80 2>/dev/null || true
  exit 1
fi

echo "==> Czekam na health (app)..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:8080/api/health" >/dev/null; then
    curl -s "http://127.0.0.1:8080/api/health"
    echo ""
    echo "==> Deploy na serwerze OK — https://${DOMAIN}"
    exit 0
  fi
  sleep 5
done

echo "==> Health timeout. Kontenery:"
docker compose ps
docker compose logs --tail=50
exit 1
