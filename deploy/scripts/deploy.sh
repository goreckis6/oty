#!/usr/bin/env bash
# Deploy on VPS — stop legacy YTDown stack, start Caddy + static placeholder.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-}"

cd "$APP_DIR"
mkdir -p deploy/caddy public downloads

echo "==> Stopping legacy containers (ytdown / home-proxy)..."
docker compose down 2>/dev/null || true
docker compose -f docker-compose.vps-proxy.yml down 2>/dev/null || true
docker rm -f ytdown ytdown-caddy ytdown-bgutil site-caddy 2>/dev/null || true

if [ -n "$ACME_EMAIL" ]; then
  cat > deploy/caddy/Caddyfile <<EOF
{
	email ${ACME_EMAIL}
}

${DOMAIN} {
	root * /srv
	file_server
}
EOF
else
  cat > deploy/caddy/Caddyfile <<EOF
${DOMAIN} {
	root * /srv
	file_server
}
EOF
fi

echo "==> Starting Caddy (placeholder site)..."
docker compose up -d --remove-orphans

echo "==> Deploy OK — https://${DOMAIN}"
docker compose ps
