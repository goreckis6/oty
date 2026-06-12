#!/usr/bin/env bash
# Uruchamiane na workerze po rsync (lokalnie lub przez SSH).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
WORKER_ID="${WORKER_ID:-w1}"

cd "$APP_DIR"
mkdir -p downloads
export WORKER_ID

docker compose -f docker-compose.yml -f docker-compose.worker.yml up -d --build

echo "==> Health:"
curl -sf "http://127.0.0.1:8082/api/health"
echo ""
