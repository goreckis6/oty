#!/usr/bin/env bash
# Deploy on VPS — Caddy + frontend + API (TMDB + torrent search)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-localhost}"
DOMAIN="$(printf '%s' "$DOMAIN" | tr -d '\n\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's|https\?://||' -e 's|/$||')"
ACME_EMAIL="${ACME_EMAIL:-}"
DATA_SOURCE="${DATA_SOURCE:-sqlite}"
TMDB_API_KEY="${TMDB_API_KEY:-}"
TORRENT_SOURCE="${TORRENT_SOURCE:-apibay}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
JWT_SECRET="${JWT_SECRET:-change-me-in-production}"
SITE_NAME="${SITE_NAME:-YTS}"
SITE_TAGLINE="${SITE_TAGLINE:-HD movies at the smallest file size}"
SITE_URL="${SITE_URL:-https://${DOMAIN}}"
SITE_URL="$(printf '%s' "$SITE_URL" | tr -d '\n\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's|/$||')"

cd "$APP_DIR"
mkdir -p deploy/caddy public/js public/css public/downloads public/uploads backend/data

DB_FILE="backend/data/movies.db"
DB_SIZE_BEFORE=0
if [ -f "$DB_FILE" ]; then
  DB_SIZE_BEFORE=$(stat -c%s "$DB_FILE")
  echo "==> SQLite database preserved ($(du -h "$DB_FILE" | awk '{print $1}'), ${DB_SIZE_BEFORE} bytes)"
else
  echo "==> No movies.db yet — database starts empty; add movies via admin scraping"
fi

if ! grep -q './backend/data:/app/data' docker-compose.yml; then
  echo "FATAL: docker-compose.yml must mount ./backend/data:/app/data — deploy aborted to protect movies.db" >&2
  exit 1
fi

echo "==> Deploy preserves on VPS: backend/data/ (movies.db + scraped data), admin site files, uploads/, downloads/, .well-known/"

cat > public/js/config.js <<EOF
window.YTS_CONFIG = {
  apiBase: "/api/v1",
  siteUrl: "${SITE_URL}",
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

echo "==> Stopping legacy containers (never -v — DB lives on host in backend/data/)..."
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
	handle /movies/* {
		reverse_proxy 127.0.0.1:8080
	}
	handle /sitemap* {
		reverse_proxy 127.0.0.1:8080
	}
	handle /robots.txt {
		reverse_proxy 127.0.0.1:8080
	}
	handle {
		root * /srv
		try_files {path} /index.html
		file_server
		encode gzip
	}
}
EOF

echo "==> Building and starting API + Caddy..."
export DATA_SOURCE TMDB_API_KEY TORRENT_SOURCE ADMIN_USER ADMIN_PASSWORD JWT_SECRET SITE_URL SITE_NAME SITE_TAGLINE
docker compose up -d --build --remove-orphans

echo "==> Waiting for services on VPS..."
for i in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:8080/api/v1/health" >/dev/null 2>&1; then
    echo "    API container ready (${i}x2s)"
    break
  fi
  sleep 2
done

if [ "$DB_SIZE_BEFORE" -gt 0 ]; then
  if [ ! -f "$DB_FILE" ]; then
    echo "FATAL: movies.db missing after deploy — aborting" >&2
    exit 1
  fi
  DB_SIZE_AFTER=$(stat -c%s "$DB_FILE")
  if [ "$DB_SIZE_AFTER" -lt "$DB_SIZE_BEFORE" ]; then
    echo "FATAL: movies.db shrank during deploy (${DB_SIZE_BEFORE} -> ${DB_SIZE_AFTER} bytes)" >&2
    exit 1
  fi
  echo "==> Database integrity check OK (${DB_SIZE_AFTER} bytes)"
fi

echo "==> Deploy OK — https://${DOMAIN}"
echo "    API: https://${DOMAIN}/api/v1/"
echo "    Admin: https://${DOMAIN}/twojastara"
docker compose ps
