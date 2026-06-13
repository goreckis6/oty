#!/usr/bin/env bash
# Na VPS: Caddy proxy → backend na domowym PC (Tailscale / SSH tunnel / VPN).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-yts.cool}"
ACME_EMAIL="${ACME_EMAIL:-}"
HOME_BACKEND_URL="${HOME_BACKEND_URL:?Ustaw HOME_BACKEND_URL, np. http://100.x.x.x:8080}"

cd "$APP_DIR"
mkdir -p deploy/caddy

if [[ "$HOME_BACKEND_URL" != http://* && "$HOME_BACKEND_URL" != https://* ]]; then
  HOME_BACKEND_URL="http://${HOME_BACKEND_URL}"
fi

if [[ "$HOME_BACKEND_URL" != */8080 && "$HOME_BACKEND_URL" != *:8080/* ]]; then
  echo "==> UWAGA: backend zwykle nasłuchuje na :8080"
fi

# Caddy w Dockerze nie widzi 127.0.0.1 hosta — tunel SSH jest na VPS, nie w kontenerze.
CADDY_BACKEND_URL="$HOME_BACKEND_URL"
if [[ "$HOME_BACKEND_URL" =~ ^https?://127\.0\.0\.1:([0-9]+)/?$ ]]; then
  CADDY_BACKEND_URL="http://host.docker.internal:${BASH_REMATCH[1]}"
  echo "==> Docker Caddy → ${CADDY_BACKEND_URL} (host VPS, port tunelu SSH)"
fi

if [ -n "$ACME_EMAIL" ]; then
  cat > deploy/caddy/Caddyfile.runtime <<EOF
{
	email ${ACME_EMAIL}
}

${DOMAIN} {
	reverse_proxy ${CADDY_BACKEND_URL} {
		transport http {
			read_timeout 3600s
			write_timeout 3600s
		}
	}
}
EOF
else
  cat > deploy/caddy/Caddyfile.runtime <<EOF
${DOMAIN} {
	reverse_proxy ${CADDY_BACKEND_URL} {
		transport http {
			read_timeout 3600s
			write_timeout 3600s
		}
	}
}
EOF
fi

echo "==> Caddy → ${HOME_BACKEND_URL}"
echo "==> Uruchom na VPS:"
echo "    cd ${APP_DIR} && docker compose -f docker-compose.vps-proxy.yml up -d"
echo "==> Zatrzymaj stary stack (jeśli działa): docker compose down"
