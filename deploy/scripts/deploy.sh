#!/usr/bin/env bash
# Deploy on VPS — Caddy + YTS frontend, optional API reverse proxy.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-}"
YTS_API_URL="${YTS_API_URL:-}"
YTS_API_BACKEND="${YTS_API_BACKEND:-}"
SITE_NAME="${SITE_NAME:-YTS}"
SITE_TAGLINE="${SITE_TAGLINE:-HD movies at the smallest file size}"

cd "$APP_DIR"
mkdir -p deploy/caddy public/js public/css public/downloads

# Frontend config — API base URL
API_BASE="/api/v2"
if [ -n "$YTS_API_URL" ]; then
  API_BASE="$YTS_API_URL"
fi

cat > public/js/config.js <<EOF
window.YTS_CONFIG = {
  apiBase: "${API_BASE}",
  siteName: "${SITE_NAME}",
  siteTagline: "${SITE_TAGLINE}",
  trackers: [
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.coppersurfer.tk:6969"
  ]
};
EOF

echo "==> Stopping legacy containers..."
docker compose down 2>/dev/null || true
docker compose -f docker-compose.vps-proxy.yml down 2>/dev/null || true
docker rm -f ytdown ytdown-caddy ytdown-bgutil site-caddy 2>/dev/null || true

# Caddyfile — optional reverse proxy to local/remote API backend
PROXY_BLOCK=""
if [ -n "$YTS_API_BACKEND" ]; then
  BACKEND="${YTS_API_BACKEND}"
  [[ "$BACKEND" != http* ]] && BACKEND="http://${BACKEND}"
  PROXY_BLOCK="
	handle /api/v2/* {
		reverse_proxy ${BACKEND}
	}"
  echo "==> API proxy: /api/v2/* → ${BACKEND}"
fi

GLOBAL_BLOCK=""
if [ -n "$ACME_EMAIL" ]; then
  GLOBAL_BLOCK="{
	email ${ACME_EMAIL}
}"
fi

cat > deploy/caddy/Caddyfile <<EOF
${GLOBAL_BLOCK}

${DOMAIN} {
	${PROXY_BLOCK}
	root * /srv
	file_server
	encode gzip
}
EOF

echo "==> Starting Caddy..."
docker compose up -d --remove-orphans

echo "==> Deploy OK — https://${DOMAIN}"
echo "    API base: ${API_BASE}"
docker compose ps
