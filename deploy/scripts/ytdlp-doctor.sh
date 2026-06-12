#!/usr/bin/env bash
# Diagnostyka YouTube / yt-dlp na serwerze
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
cd "$APP_DIR"

echo "=== yt-dlp doctor ==="
if [[ -f "${APP_DIR}/.venv/bin/yt-dlp" ]]; then
  echo "yt-dlp: $("${APP_DIR}/.venv/bin/yt-dlp" --version)"
else
  echo "yt-dlp: brak venv w ${APP_DIR}/.venv"
fi
echo "node: $(command -v node || echo brak) $(node --version 2>/dev/null || true)"
echo "deno: $(command -v deno || echo brak) $(deno --version 2>/dev/null | head -1 || true)"
echo "cookies: ${YTDOWN_COOKIES_FILE:-brak} $([[ -f "${YTDOWN_COOKIES_FILE:-}" ]] && echo OK || echo nie)"

if [[ -f /etc/ytdown/env ]]; then
  echo "--- /etc/ytdown/env ---"
  grep -E '^YTDOWN_(JS|REMOTE|YOUTUBE|COOKIES)' /etc/ytdown/env || true
fi

echo "--- health ---"
curl -sf "http://127.0.0.1:${YTDOWN_PORT:-8080}/api/health" || echo "health FAIL"

echo "--- test extract ---"
if [[ -f "${APP_DIR}/.venv/bin/yt-dlp" ]]; then
  "${APP_DIR}/.venv/bin/yt-dlp" \
    --js-runtimes deno --js-runtimes node \
    --remote-components ejs:github \
    --extractor-args "youtube:player_client=web,android,ios" \
    --skip-download -j "https://www.youtube.com/watch?v=04mwz6vfQnY" 2>&1 | head -5 || true
fi
