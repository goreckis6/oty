#!/usr/bin/env bash
# Deploy na jednym VPS (bez load balancera).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
PUBLIC_PORT="${PUBLIC_PORT:-8082}"

cd "$APP_DIR"
mkdir -p downloads

if ! command -v docker >/dev/null; then
  apt-get update -qq
  apt-get install -y docker.io docker-compose-v2
  systemctl enable --now docker
fi

export YTDOWN_PUBLIC_PORT="$PUBLIC_PORT"
docker compose up -d --build

echo "==> Health:"
curl -sf "http://127.0.0.1:${PUBLIC_PORT}/api/health"
echo ""
