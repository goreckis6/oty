#!/usr/bin/env bash
# Deploy on VPS — Caddy + frontend + API (TMDB + torrent search)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-}"
DATA_SOURCE="${DATA_SOURCE:-scrape}"
TMDB_API_KEY="${TMDB_API_KEY:-}"
TORRENT_SOURCE="${TORRENT_SOURCE:-apibay}"
SITE_NAME="${SITE_NAME:-YTS}"
SITE_TAGLINE="${SITE_TAGLINE:-HD movies at the smallest file size}"

cd "$APP_DIR"
mkdir -p deploy/caddy public/js public/css public/downloads

cat > public/js/config.js <<EOF
window.YTS_CONFIG = {
  apiBase: "/api/v1",
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
docker rm -f ytdown ytdown-caddy ytdown-bgutil site-caddy site-api 2>/dev/null || true

GLOBAL_BLOCK=""
if [ -n "$ACME_EMAIL" ]; then
  GLOBAL_BLOCK="{
	email ${ACME_EMAIL}
}"
fi

cat > deploy/caddy/Caddyfile <<EOF
${GLOBAL_BLOCK}

${DOMAIN} {
	handle /api/v1/* {
		reverse_proxy 127.0.0.1:8080
	}
	root * /srv
	file_server
	encode gzip
}
EOF

echo "==> Building and starting API + Caddy..."
export DATA_SOURCE TMDB_API_KEY TORRENT_SOURCE
docker compose up -d --build --remove-orphans

echo "==> Deploy OK — https://${DOMAIN}"
echo "    API: https://${DOMAIN}/api/v1/"
echo "    Data: ${DATA_SOURCE} | Torrents: ${TORRENT_SOURCE}"
docker compose ps
