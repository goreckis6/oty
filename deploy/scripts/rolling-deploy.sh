#!/usr/bin/env bash
# Deploy worker po workerze (nie ubija wszystkich naraz).
# Użycie: ./deploy/scripts/rolling-deploy.sh w1@10.0.0.1 w2@10.0.0.2
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKERS=("$@")

if [[ ${#WORKERS[@]} -eq 0 ]]; then
  echo "Usage: $0 user@host [user@host ...]"
  exit 1
fi

for target in "${WORKERS[@]}"; do
  echo "==> Deploy $target"
  rsync -avz --exclude '.git' --exclude 'backend/.venv' --exclude 'bin' --exclude 'downloads' \
    "$ROOT/" "$target:/opt/ytdown/"
  ssh "$target" 'cd /opt/ytdown && docker compose up -d --build'
  echo "==> Czekam 60s przed następnym workerem (dokończenie jobów)..."
  sleep 60
done

echo "==> Gotowe"
