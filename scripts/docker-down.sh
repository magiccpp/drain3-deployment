#!/usr/bin/env bash
# Stop and remove the logsum container (the stats volume is kept unless you pass --purge).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
if docker compose version >/dev/null 2>&1; then docker compose down; else docker rm -f logsum; fi
[ "${1:-}" = "--purge" ] && docker volume rm logsum-data
echo "stopped. The host 'logsum' command now falls back to the local venv (if installed) or passthrough."
