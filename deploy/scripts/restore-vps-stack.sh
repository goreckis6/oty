#!/usr/bin/env bash
# Przywróć normalny stack na VPS (ytdown + bgutil + Caddy) — bez tunelu z domu.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-yts.cool}"
ACME_EMAIL="${ACME_EMAIL:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$APP_DIR"

echo "==> Zatrzymuję proxy-only (tunel home)..."
docker compose -f docker-compose.vps-proxy.yml down 2>/dev/null || true

echo "==> Przywracam Caddyfile → ytdown:8080"
if [ -n "$ACME_EMAIL" ]; then
  cat > deploy/caddy/Caddyfile.runtime <<EOF
{
	email ${ACME_EMAIL}
}

${DOMAIN} {
	reverse_proxy ytdown:8080
}
EOF
else
  cat > deploy/caddy/Caddyfile.runtime <<EOF
${DOMAIN} {
	reverse_proxy ytdown:8080
}
EOF
fi

if [[ -f .env ]] && grep -q '^YTDOWN_PROXY=' .env; then
  echo "==> Wyłączam YTDOWN_PROXY w .env (opcjonalnie usuń ręcznie)"
  sed -i 's/^YTDOWN_PROXY=.*/YTDOWN_PROXY=/' .env || true
fi

export DOMAIN ACME_EMAIL
bash "${SCRIPT_DIR}/deploy-single.sh"

echo ""
echo "==> Gotowe. Sprawdź:"
echo "    curl -s https://${DOMAIN}/api/health"
echo "    (oczekiwane: worker w1, pot_provider enabled)"
