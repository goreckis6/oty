#!/usr/bin/env bash
# Copy preserved site data from OLD VPS to NEW VPS (DB, uploads, admin files).
# Run from your laptop with SSH access to BOTH servers.
#
# Usage:
#   OLD_HOST=1.2.3.4 NEW_HOST=5.6.7.8 bash deploy/scripts/migrate-data.sh
#
# Optional:
#   OLD_USER=root NEW_USER=root
#   OLD_PATH=/opt/ytdown NEW_PATH=/opt/ytdown
#   OLD_PORT=22 NEW_PORT=22
#   SSH_KEY=~/.ssh/deploy_key
set -euo pipefail

OLD_HOST="${OLD_HOST:-}"
NEW_HOST="${NEW_HOST:-}"
OLD_USER="${OLD_USER:-root}"
NEW_USER="${NEW_USER:-root}"
OLD_PORT="${OLD_PORT:-22}"
NEW_PORT="${NEW_PORT:-22}"
OLD_PATH="${OLD_PATH:-/opt/ytdown}"
NEW_PATH="${NEW_PATH:-/opt/ytdown}"
SSH_KEY="${SSH_KEY:-}"

if [ -z "$OLD_HOST" ] || [ -z "$NEW_HOST" ]; then
  echo "Usage: OLD_HOST=<old-ip> NEW_HOST=<new-ip> bash deploy/scripts/migrate-data.sh" >&2
  exit 1
fi

ssh_old=(ssh -p "$OLD_PORT" -o StrictHostKeyChecking=accept-new)
ssh_new=(ssh -p "$NEW_PORT" -o StrictHostKeyChecking=accept-new)
if [ -n "$SSH_KEY" ]; then
  ssh_old+=(-i "$SSH_KEY")
  ssh_new+=(-i "$SSH_KEY")
fi

rsync_old() {
  local extra=()
  if [ -n "$SSH_KEY" ]; then extra=(-i "$SSH_KEY"); fi
  rsync -avz --progress -e "ssh ${extra[*]} -p ${OLD_PORT} -o StrictHostKeyChecking=accept-new" "$@"
}

rsync_new() {
  local extra=()
  if [ -n "$SSH_KEY" ]; then extra=(-i "$SSH_KEY"); fi
  rsync -avz --progress -e "ssh ${extra[*]} -p ${NEW_PORT} -o StrictHostKeyChecking=accept-new" "$@"
}

remote_old() { "${ssh_old[@]}" "${OLD_USER}@${OLD_HOST}" "$@"; }
remote_new() { "${ssh_new[@]}" "${NEW_USER}@${NEW_HOST}" "$@"; }

STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

echo "==> Migrating site data"
echo "    FROM ${OLD_USER}@${OLD_HOST}:${OLD_PATH}"
echo "    TO   ${NEW_USER}@${NEW_HOST}:${NEW_PATH}"

remote_new "mkdir -p '${NEW_PATH}/backend/data' '${NEW_PATH}/public/uploads' '${NEW_PATH}/public/downloads' '${NEW_PATH}/public/.well-known'"

if remote_old "test -f '${OLD_PATH}/backend/data/movies.db'"; then
  echo "==> Sync backend/data/ (movies.db + scrape metadata)..."
  rsync_old "${OLD_USER}@${OLD_HOST}:${OLD_PATH}/backend/data/" "${STAGE}/backend-data/"
  rsync_new "${STAGE}/backend-data/" "${NEW_USER}@${NEW_HOST}:${NEW_PATH}/backend/data/"
else
  echo "WARN: no movies.db on old server — skipping database" >&2
fi

for subdir in uploads downloads .well-known; do
  if remote_old "test -d '${OLD_PATH}/public/${subdir}' && [ -n \"\$(ls -A '${OLD_PATH}/public/${subdir}' 2>/dev/null)\" ]"; then
    echo "==> Sync public/${subdir}/..."
    rsync_old "${OLD_USER}@${OLD_HOST}:${OLD_PATH}/public/${subdir}/" "${STAGE}/${subdir}/"
    rsync_new "${STAGE}/${subdir}/" "${NEW_USER}@${NEW_HOST}:${NEW_PATH}/public/${subdir}/"
  fi
done

echo "==> Sync admin / verification files in public/ (not index.html)..."
while IFS= read -r rel; do
  [ -z "$rel" ] && continue
  rel="${rel#./}"
  echo "    ${rel}"
  rsync_old "${OLD_USER}@${OLD_HOST}:${OLD_PATH}/public/${rel}" "${STAGE}/public-files/${rel}"
  remote_new "mkdir -p '${NEW_PATH}/public/$(dirname "${rel}")'"
  rsync_new "${STAGE}/public-files/${rel}" "${NEW_USER}@${NEW_HOST}:${NEW_PATH}/public/${rel}"
done < <(remote_old "cd '${OLD_PATH}/public' && find . -maxdepth 1 -type f ! -name 'index.html' -print")

echo "==> Verify on new server..."
remote_new "
  if [ -f '${NEW_PATH}/backend/data/movies.db' ]; then
    echo \"movies.db: \$(du -h '${NEW_PATH}/backend/data/movies.db' | awk '{print \$1}')\"
    if command -v python3 >/dev/null; then
      python3 - <<'PY'
import sqlite3
db = sqlite3.connect('${NEW_PATH}/backend/data/movies.db')
print('integrity:', db.execute('PRAGMA integrity_check').fetchone()[0])
print('movies:', db.execute('SELECT COUNT(*) FROM movies').fetchone()[0])
PY
    else
      sqlite3 '${NEW_PATH}/backend/data/movies.db' 'PRAGMA integrity_check; SELECT COUNT(*) FROM movies;'
    fi
  else
    echo 'WARN: movies.db missing on new server'
  fi
"

echo ""
echo "==> Data migration OK"
echo "    1. GitHub Secret DEPLOY_HOST → ${NEW_HOST}"
echo "    2. Run Deploy workflow"
echo "    3. Test with: curl -sk --resolve 'DOMAIN:443:${NEW_HOST}' https://DOMAIN/api/v1/health"
echo "    4. Switch DNS, then shutdown-old-server.sh on old VPS"
