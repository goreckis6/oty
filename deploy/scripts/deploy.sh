#!/usr/bin/env bash
# Deploy on VPS — Caddy + frontend + API (TMDB + torrent search)
set -euo pipefail

DEPLOY_START=$(date +%s)

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
TOKEN_TTL_HOURS="${TOKEN_TTL_HOURS:-720}"
ADMIN_ALLOWED_IPS="${ADMIN_ALLOWED_IPS:-}"
SITE_NAME="${SITE_NAME:-YTS}"
SITE_TAGLINE="${SITE_TAGLINE:-HD movies at the smallest file size}"
SITE_URL="${SITE_URL:-https://${DOMAIN}}"
SITE_URL="$(printf '%s' "$SITE_URL" | tr -d '\n\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's|/$||')"

caddy_url() {
  curl -4 -sfk --max-time "${1:-20}" --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}${2}"
}

response_contains() {
  local needle="$1"
  shift
  local body
  body=$("$@" 2>/dev/null || true)
  case "$body" in *"$needle"*) return 0 ;; *) return 1 ;; esac
}

api_running() {
  [ "$(docker inspect -f '{{.State.Running}}' site-api 2>/dev/null || echo false)" = "true" ]
}

caddy_running() {
  [ "$(docker inspect -f '{{.State.Running}}' site-caddy 2>/dev/null || echo false)" = "true" ]
}

api_healthy_now() {
  curl -sf --max-time 2 "http://127.0.0.1:8080/api/v1/health" >/dev/null 2>&1
}

env_fingerprint() {
  printf '%s|' \
    "$DATA_SOURCE" "$TMDB_API_KEY" "$TORRENT_SOURCE" "$ADMIN_USER" \
    "$ADMIN_PASSWORD" "$JWT_SECRET" "$TOKEN_TTL_HOURS" "$ADMIN_ALLOWED_IPS" \
    "$SITE_URL" "$SITE_NAME" "$SITE_TAGLINE" | sha256sum | awk '{print $1}'
}

reload_caddy() {
  if caddy_running; then
    docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null \
      || docker compose restart caddy
  fi
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
docker rm -f ytdown ytdown-caddy ytdown-bgutil 2>/dev/null || true

CADDY_RUNNING=false
if [ "$(docker inspect -f '{{.State.Running}}' site-caddy 2>/dev/null || echo false)" = "true" ]; then
  CADDY_RUNNING=true
fi

if [ "$CADDY_RUNNING" = "false" ]; then
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
fi

GLOBAL_BLOCK=""
if [ -n "$ACME_EMAIL" ]; then
  GLOBAL_BLOCK="{
	email ${ACME_EMAIL}
}"
fi

CADDYFILE="deploy/caddy/Caddyfile"
CADDY_TMP="$(mktemp)"
cat > "$CADDY_TMP" <<EOF
${GLOBAL_BLOCK}

${DOMAIN} {
	encode gzip

	handle /api/v1/* {
		reverse_proxy 127.0.0.1:8080 {
			transport http {
				read_timeout 30m
				write_timeout 30m
			}
			header_up X-Forwarded-For {remote_host}
			header_up X-Real-IP {remote_host}
		}
	}

	handle /movies/* {
		reverse_proxy 127.0.0.1:8080 {
			header_up X-Forwarded-For {remote_host}
			header_up X-Real-IP {remote_host}
		}
	}

	@spa path / /browse /browse/* /twojastara /twojastara/*
	handle @spa {
		reverse_proxy 127.0.0.1:8080 {
			header_up X-Forwarded-For {remote_host}
			header_up X-Real-IP {remote_host}
		}
	}

	@static path /css/* /js/* /uploads/*
	handle @static {
		root * /srv
		header Cache-Control "public, max-age=604800, immutable"
		file_server
	}

	@seo path /robots.txt /sitemap.xml /sitemap*
	handle @seo {
		reverse_proxy 127.0.0.1:8080 {
			header_up X-Forwarded-For {remote_host}
			header_up X-Real-IP {remote_host}
		}
	}

	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}
}
EOF

CADDY_CHANGED=1
if [ -f "$CADDYFILE" ] && cmp -s "$CADDY_TMP" "$CADDYFILE"; then
  CADDY_CHANGED=0
  rm -f "$CADDY_TMP"
else
  mv "$CADDY_TMP" "$CADDYFILE"
fi

if [ ! -f public/index.html ]; then
  echo "FATAL: missing public/index.html — cannot serve frontend" >&2
  exit 1
fi

api_source_hash() {
  find backend -type f \( -name '*.py' -o -name 'requirements.txt' -o -name 'Dockerfile' \) -print0 \
    | sort -z | xargs -0 sha256sum 2>/dev/null | sha256sum | awk '{print $1}'
}

HASH_FILE="backend/data/.deploy-api-hash"
ENV_HASH_FILE="backend/data/.deploy-env-hash"
CURRENT_HASH="$(api_source_hash)"
CURRENT_ENV_HASH="$(env_fingerprint)"

NEED_BUILD=1
if [ -f "$HASH_FILE" ] && [ "$(cat "$HASH_FILE")" = "$CURRENT_HASH" ]; then
  NEED_BUILD=0
fi

NEED_API_RESTART=0
if [ "$NEED_BUILD" -eq 1 ] || ! api_running; then
  NEED_API_RESTART=1
elif [ ! -f "$ENV_HASH_FILE" ] || [ "$(cat "$ENV_HASH_FILE")" != "$CURRENT_ENV_HASH" ]; then
  NEED_API_RESTART=1
fi

FAST_DEPLOY=0
if [ "$NEED_BUILD" -eq 0 ] && [ "$NEED_API_RESTART" -eq 0 ] && api_healthy_now; then
  FAST_DEPLOY=1
fi

echo "==> Starting API + Caddy..."
export DATA_SOURCE TMDB_API_KEY TORRENT_SOURCE ADMIN_USER ADMIN_PASSWORD JWT_SECRET TOKEN_TTL_HOURS ADMIN_ALLOWED_IPS SITE_URL SITE_NAME SITE_TAGLINE
if [ "$FAST_DEPLOY" -eq 1 ]; then
  echo "    Fast deploy — static/config only (no container restart)"
  if [ "$CADDY_CHANGED" -eq 1 ]; then
    reload_caddy
  elif ! caddy_running; then
    docker compose up -d caddy --no-recreate --remove-orphans
  fi
elif [ "$NEED_BUILD" -eq 1 ]; then
  echo "    API code changed — building image"
  docker compose up -d --build --remove-orphans
  echo "$CURRENT_HASH" > "$HASH_FILE"
  echo "$CURRENT_ENV_HASH" > "$ENV_HASH_FILE"
elif [ "$NEED_API_RESTART" -eq 1 ]; then
  echo "    API env or state changed — recreating API container (no image build)"
  docker compose up -d --no-build --remove-orphans
  echo "$CURRENT_ENV_HASH" > "$ENV_HASH_FILE"
else
  echo "    API unchanged — skipping image build and container recreate"
  docker compose up -d --no-recreate --remove-orphans
  echo "$CURRENT_ENV_HASH" > "$ENV_HASH_FILE"
fi

if [ "$FAST_DEPLOY" -eq 0 ] && [ "$CADDY_CHANGED" -eq 1 ]; then
  reload_caddy
fi

if [ "$(docker inspect -f '{{.State.Running}}' site-caddy 2>/dev/null || echo false)" != "true" ]; then
  echo "FATAL: Caddy container is not running" >&2
  docker compose logs caddy --tail 40 || true
  exit 1
fi

echo "==> Waiting for services on VPS..."
WAIT_API=0
if [ "$FAST_DEPLOY" -eq 1 ]; then
  WAIT_API=0
elif [ "$NEED_BUILD" -eq 1 ] || [ "$NEED_API_RESTART" -eq 1 ]; then
  WAIT_API=1
elif ! api_healthy_now; then
  WAIT_API=1
fi

API_OK=0
if [ "$WAIT_API" -eq 0 ]; then
  if api_healthy_now; then
    echo "    API already healthy — skipping wait"
    API_OK=1
  else
    WAIT_API=1
  fi
fi

if [ "$WAIT_API" -eq 1 ]; then
  for i in $(seq 1 60); do
    if api_healthy_now; then
      echo "    API container ready (${i}x1s)"
      API_OK=1
      break
    fi
    sleep 1
  done
fi

if [ "$API_OK" -ne 1 ]; then
  echo "FATAL: API health check failed after deploy" >&2
  docker compose ps || true
  docker compose logs api --tail 80 || true
  exit 1
fi

if [ "$FAST_DEPLOY" -eq 0 ]; then
  if ! response_contains '"status"' curl -sf --max-time 3 http://127.0.0.1:8080/api/v1/health; then
    echo "FATAL: API health endpoint returned unexpected response" >&2
    exit 1
  fi
  if ! response_contains '<!DOCTYPE html' curl -sf --max-time 3 http://127.0.0.1:8080/; then
    echo "FATAL: homepage is not serving HTML from API fallback" >&2
    exit 1
  fi
  echo "==> Homepage HTML OK"
fi

if ! response_contains '"status"' caddy_url 10 /api/v1/health; then
  echo "FATAL: API not reachable through Caddy (HTTPS)" >&2
  docker compose logs caddy --tail 40 || true
  exit 1
fi
if [ "$FAST_DEPLOY" -eq 0 ] && ! response_contains '<!DOCTYPE html' caddy_url 10 /; then
  echo "FATAL: homepage not serving HTML through Caddy" >&2
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

echo "==> Deploy OK — https://${DOMAIN} ($(($(date +%s) - DEPLOY_START))s)"
echo "    API: https://${DOMAIN}/api/v1/"
echo "    Admin: https://${DOMAIN}/twojastara"
docker compose ps

if [ ! -f "backend/data/.deploy-boot-installed" ] || ! cmp -s "deploy/systemd/ytdown.service" "backend/data/.deploy-boot-unit-src" 2>/dev/null; then
  echo "==> Installing boot service (auto-start after VPS reboot)..."
  bash "${APP_DIR}/deploy/scripts/install-boot-service.sh"
  cp "deploy/systemd/ytdown.service" "backend/data/.deploy-boot-unit-src"
  touch "backend/data/.deploy-boot-installed"
else
  echo "==> Boot service unchanged — skipping"
fi
