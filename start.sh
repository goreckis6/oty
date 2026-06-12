#!/usr/bin/env bash
# Lokalny development — to samo co na serwerze, z --reload
set -euo pipefail
cd "$(dirname "$0")"
export YTDOWN_DEV=1
export YTDOWN_HOST="${YTDOWN_HOST:-127.0.0.1}"
export YTDOWN_PORT="${YTDOWN_PORT:-3000}"
exec ./scripts/run.sh
