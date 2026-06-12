#!/usr/bin/env bash
# Deploy bez Dockera: Python jak start.sh + Caddy na hoście + systemd.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
DOMAIN="${DOMAIN:-yts.cool}"
ACME_EMAIL="${ACME_EMAIL:-}"
APP_PORT="${APP_PORT:-8080}"

cd "$APP_DIR"
export DEBIAN_FRONTEND=noninteractive

install_deps() {
  echo "==> Pakiety (Python, ffmpeg, Caddy, Node)..."
  apt-get update -qq
  apt-get install -y -qq \
    python3 python3-venv python3-pip \
    ffmpeg curl caddy rsync unzip ca-certificates \
    nodejs
  systemctl enable caddy
}

install_deno() {
  if command -v deno >/dev/null; then
    return 0
  fi
  echo "==> Instalacja Deno (yt-dlp YouTube EJS)..."
  local arch url
  case "$(uname -m)" in
    x86_64) arch="x86_64-unknown-linux-gnu" ;;
    aarch64|arm64) arch="aarch64-unknown-linux-gnu" ;;
    *) echo "==> Pomijam Deno (nieznana architektura)"; return 0 ;;
  esac
  url="https://github.com/denoland/deno/releases/latest/download/deno-${arch}.zip"
  curl -fsSL "$url" -o /tmp/deno.zip
  unzip -qo /tmp/deno.zip -d /usr/local/bin
  chmod +x /usr/local/bin/deno
  rm -f /tmp/deno.zip
}

setup_firewall() {
  if ! command -v ufw >/dev/null; then
    return 0
  fi
  echo "==> Firewall (80, 443, SSH)..."
  ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
}

ensure_env_var() {
  local key="$1"
  local value="$2"
  local file="/etc/ytdown/env"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

setup_env() {
  mkdir -p /etc/ytdown "$APP_DIR/downloads" "$APP_DIR/secrets"
  if [[ ! -f /etc/ytdown/env ]]; then
    cp "$APP_DIR/deploy/env.example" /etc/ytdown/env
  fi
  ensure_env_var "YTDOWN_HOST" "127.0.0.1"
  ensure_env_var "YTDOWN_PORT" "${APP_PORT}"
  ensure_env_var "YTDOWN_DOWNLOADS_DIR" "${APP_DIR}/downloads"
  ensure_env_var "YTDOWN_JS_RUNTIMES" "deno,node"
  ensure_env_var "YTDOWN_REMOTE_COMPONENTS" "ejs:github"
  ensure_env_var "YTDOWN_YOUTUBE_CLIENTS" "web,android,ios"
  ensure_env_var "YTDOWN_SLEEP_INTERVAL_REQUESTS" "1"
  if [[ -f "$APP_DIR/secrets/cookies.txt" ]]; then
    ensure_env_var "YTDOWN_COOKIES_FILE" "${APP_DIR}/secrets/cookies.txt"
  fi
}

setup_caddy() {
  local caddyfile="/etc/caddy/Caddyfile"
  if [[ -n "$ACME_EMAIL" ]]; then
    cat > "$caddyfile" <<EOF
{
	email ${ACME_EMAIL}
}

${DOMAIN} {
	reverse_proxy 127.0.0.1:${APP_PORT}
}
EOF
  else
    cat > "$caddyfile" <<EOF
${DOMAIN} {
	reverse_proxy 127.0.0.1:${APP_PORT}
}
EOF
  fi
  systemctl restart caddy || systemctl start caddy
}

setup_systemd() {
  cat > /etc/systemd/system/ytdown.service <<EOF
[Unit]
Description=YTDown YouTube downloader
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=-/etc/ytdown/env
ExecStart=${APP_DIR}/scripts/run.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  chmod +x "${APP_DIR}/scripts/run.sh"
  systemctl daemon-reload
  systemctl enable ytdown
}

install_python_deps() {
  echo "==> Instalacja zależności Python..."
  if [[ ! -d "${APP_DIR}/.venv" ]]; then
    python3 -m venv "${APP_DIR}/.venv"
  fi
  "${APP_DIR}/.venv/bin/pip" install -q --upgrade pip
  "${APP_DIR}/.venv/bin/pip" install -q --upgrade -r "${APP_DIR}/backend/requirements.txt"
  echo "==> yt-dlp: $("${APP_DIR}/.venv/bin/yt-dlp" --version)"
  echo "==> node: $(command -v node || echo brak) $(node --version 2>/dev/null || true)"
  echo "==> deno: $(command -v deno || echo brak) $(deno --version 2>/dev/null | head -1 || true)"
}

stop_docker_if_running() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && [[ -f docker-compose.yml ]]; then
    if docker compose ps -q 2>/dev/null | grep -q .; then
      echo "==> Zatrzymuję kontenery Docker (przechodzimy na native)..."
      docker compose down 2>/dev/null || true
    fi
  fi
}

install_deps
install_deno
setup_firewall
setup_env
setup_caddy
setup_systemd
install_python_deps
systemctl restart ytdown
sleep 3
stop_docker_if_running

echo "==> Czekam na health..."
for i in $(seq 1 36); do
  health="$(curl -sf "http://127.0.0.1:${APP_PORT}/api/health" 2>/dev/null || true)"
  if [[ -n "$health" ]]; then
    echo "$health"
    if echo "$health" | grep -q '"js_runtimes"'; then
      echo "==> Deploy native OK — https://${DOMAIN}"
      systemctl is-active ytdown caddy
      exit 0
    fi
    if [[ "$i" -ge 6 ]]; then
      echo "==> App działa (stary health JSON?) — https://${DOMAIN}"
      systemctl is-active ytdown caddy
      exit 0
    fi
  fi
  if [[ "$i" = 5 || "$i" = 15 ]]; then
    systemctl status ytdown --no-pager -l || true
    journalctl -u ytdown -n 20 --no-pager || true
  fi
  sleep 5
done

echo "==> Health timeout"
systemctl status ytdown --no-pager || true
systemctl status caddy --no-pager || true
journalctl -u ytdown -n 40 --no-pager || true
exit 1
