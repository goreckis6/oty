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

caddy_url() {
  curl -4 -sfk --max-time 20 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}$1"
}

response_contains() {
  local needle="$1"
  shift
  local body
  body=$("$@" 2>/dev/null || true)
  case "$body" in *"$needle"*) return 0 ;; *) return 1 ;; esac
}

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

echo "==> Freeing HTTP/HTTPS ports for Caddy..."
docker ps -q --filter "publish=80" | xargs -r docker rm -f 2>/dev/null || true
docker ps -q --filter "publish=443" | xargs -r docker rm -f 2>/dev/null || true
if command -v ss >/dev/null 2>&1; then
  for port in 80 443; do
    if ss -tln | grep -q ":${port} "; then
      pids=$(ss -tlnp "sport = :${port}" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)
      for pid in $pids; do
        comm=$(ps -p "$pid" -o comm= 2>/dev/null || true)
        case "$comm" in
          caddy|caddy-*|docker-proxy)
            echo "    Stopping stale ${comm} (pid ${pid}) on port ${port}"
            kill "$pid" 2>/dev/null || true
            ;;
        esac
      done
    fi
  done
  sleep 1
  for port in 80 443; do
    if ss -tln | grep -q ":${port} "; then
      echo "FATAL: port ${port} still in use — cannot start Caddy" >&2
      ss -tlnp "sport = :${port}" 2>&1 || true
      exit 1
    fi
  done
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
	encode gzip

	handle /api/v1/* {
		reverse_proxy 127.0.0.1:8080
	}

	handle /movies/* {
		reverse_proxy 127.0.0.1:8080
	}

	@seo path /robots.txt /sitemap.xml /sitemap*
	handle @seo {
		reverse_proxy 127.0.0.1:8080
	}

	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}
}
EOF

if [ ! -f public/index.html ]; then
  echo "FATAL: missing public/index.html — cannot serve frontend" >&2
  exit 1
fi

echo "==> Building and starting API + Caddy..."
export DATA_SOURCE TMDB_API_KEY TORRENT_SOURCE ADMIN_USER ADMIN_PASSWORD JWT_SECRET SITE_URL SITE_NAME SITE_TAGLINE
docker compose up -d --build --remove-orphans

if [ "$(docker inspect -f '{{.State.Running}}' site-caddy 2>/dev/null || echo false)" != "true" ]; then
  echo "FATAL: Caddy container is not running" >&2
  docker compose logs caddy --tail 40 || true
  exit 1
fi

echo "==> Waiting for services on VPS..."
API_OK=0
for i in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:8080/api/v1/health" >/dev/null 2>&1; then
    echo "    API container ready (${i}x2s)"
    API_OK=1
    break
  fi
  sleep 2
done

if [ "$API_OK" -ne 1 ]; then
  echo "FATAL: API health check failed after deploy" >&2
  docker compose ps || true
  docker compose logs api --tail 80 || true
  exit 1
fi

if ! response_contains '"status"' curl -sf http://127.0.0.1:8080/api/v1/health; then
  echo "FATAL: API health endpoint returned unexpected response" >&2
  curl -sv "http://127.0.0.1:8080/api/v1/health" 2>&1 | tail -20 || true
  exit 1
fi

if ! response_contains '<!DOCTYPE html' curl -sf http://127.0.0.1:8080/; then
  echo "FATAL: homepage is not serving HTML from API fallback" >&2
  curl -sv "http://127.0.0.1:8080/" 2>&1 | tail -20 || true
  exit 1
fi
echo "==> Homepage HTML OK"

if ! response_contains '"status"' caddy_url /api/v1/health; then
  echo "FATAL: API not reachable through Caddy (HTTPS)" >&2
  curl -4 -svk --max-time 20 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/v1/health" 2>&1 | tail -20 || true
  docker compose logs caddy --tail 40 || true
  exit 1
fi
if ! response_contains '"movie_count"' caddy_url /api/v1/list_movies.json?limit=1; then
  echo "FATAL: movies API not returning JSON through Caddy" >&2
  curl -4 -svk --max-time 20 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/v1/list_movies.json?limit=1" 2>&1 | tail -20 || true
  exit 1
fi
if ! response_contains '<!DOCTYPE html' caddy_url /; then
  echo "FATAL: homepage not serving HTML through Caddy" >&2
  curl -4 -svk --max-time 20 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/" 2>&1 | tail -20 || true
  exit 1
fi
echo "==> API routing through Caddy OK"

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

echo "==> Installing boot service (auto-start after VPS reboot)..."
bash "${APP_DIR}/deploy/scripts/install-boot-service.sh"
