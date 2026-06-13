#!/usr/bin/env bash
# Diagnostyka home worker + Caddy na VPS.
set -euo pipefail

TUNNEL_PORT="${TUNNEL_PORT:-28080}"
DOMAIN="${DOMAIN:-yts.cool}"

echo "=== 1. Tunel SSH na hoście VPS (port ${TUNNEL_PORT}) ==="
if curl -sf --max-time 5 "http://127.0.0.1:${TUNNEL_PORT}/api/health"; then
  echo ""
  echo "OK: tunel działa"
else
  echo "BŁĄD: brak odpowiedzi na 127.0.0.1:${TUNNEL_PORT}"
  echo "  → Uruchom u siebie: REMOTE_PORT=${TUNNEL_PORT} ./scripts/connect-home-to-vps.sh"
fi

echo ""
echo "=== 2. Caddyfile ==="
cat deploy/caddy/Caddyfile.runtime 2>/dev/null || echo "brak pliku"

echo ""
echo "=== 3. Kontener Caddy ==="
docker ps --filter name=ytdown-caddy --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true

echo ""
echo "=== 4. Logi Caddy (ostatnie 20) ==="
docker logs ytdown-caddy --tail 20 2>/dev/null || echo "brak kontenera"

echo ""
echo "=== 5. HTTPS ${DOMAIN} ==="
curl -sS -w "\nHTTP:%{http_code}\n" --max-time 10 "https://${DOMAIN}/api/health" || true
