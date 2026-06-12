#!/usr/bin/env bash
# Deploy na jednym VPS (bez load balancera).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
PUBLIC_PORT="${PUBLIC_PORT:-3000}"

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

install_docker

export YTDOWN_PUBLIC_PORT="$PUBLIC_PORT"

echo "==> Docker build & start (może potrwać 2–5 min przy pierwszym razie)..."
if ! docker compose up -d --build; then
  echo "==> BŁĄD docker compose. Logi:"
  docker compose logs --tail=80 2>/dev/null || true
  exit 1
fi

echo "==> Czekam na health..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PUBLIC_PORT}/api/health" >/dev/null; then
    curl -s "http://127.0.0.1:${PUBLIC_PORT}/api/health"
    echo ""
    echo "==> Deploy na serwerze OK"
    exit 0
  fi
  sleep 5
done

echo "==> Health timeout. Kontenery:"
docker compose ps
docker compose logs --tail=50
exit 1
