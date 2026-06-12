#!/usr/bin/env bash
# Usuwa stare pliki pobierania. Domyślnie: starsze niż 2h.
set -euo pipefail

DIR="${YTDOWN_DOWNLOADS_DIR:-/opt/ytdown/downloads}"
MAX_AGE_MIN="${YTDOWN_CLEANUP_MAX_AGE_MIN:-120}"

find "$DIR" -mindepth 1 -maxdepth 1 -type d -mmin "+$MAX_AGE_MIN" -exec rm -rf {} +
find "$DIR" -type f -mmin "+$MAX_AGE_MIN" -delete 2>/dev/null || true
