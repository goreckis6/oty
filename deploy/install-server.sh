#!/usr/bin/env bash
# One-time server setup (Ubuntu/Debian). Run as root or with sudo.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytdown}"
APP_USER="${APP_USER:-ytdown}"

echo "==> Installing system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg curl rsync git

echo "==> Creating user $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> Creating directories"
mkdir -p "$APP_DIR" /etc/ytdown
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [[ ! -f /etc/ytdown/env ]]; then
  cp "$APP_DIR/deploy/env.example" /etc/ytdown/env 2>/dev/null || true
  echo "Edit /etc/ytdown/env (host, port, cookies)"
fi

echo "==> Installing systemd service"
cp "$APP_DIR/deploy/ytdown.service" /etc/systemd/system/ytdown.service
systemctl daemon-reload
systemctl enable ytdown

echo ""
echo "Done. Next steps:"
echo "  1. Edit /etc/ytdown/env"
echo "  2. Deploy app files to $APP_DIR (GitHub Actions or rsync)"
echo "  3. Run: APP_DIR=$APP_DIR bash $APP_DIR/deploy/remote-deploy.sh"
echo "  4. Open: http://YOUR_SERVER_IP:\${YTDOWN_PORT:-8082}"
