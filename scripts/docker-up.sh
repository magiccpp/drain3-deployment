#!/usr/bin/env bash
# Build and start the logsum container, and point the host `logsum` command at it.
#   scripts/docker-up.sh [--bind 0.0.0.0] [--claude-hook-log /mnt/c/Users/<you>/.claude/hooks/logsum-hook.log]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export LOGSUM_BIND="127.0.0.1"
export OPENCODE_LOG="$HOME/.config/opencode/logsum-plugin.log"
export CLAUDE_HOOK_LOG="/dev/null"
while [ $# -gt 0 ]; do
  case "$1" in
    --bind) export LOGSUM_BIND="$2"; shift 2 ;;
    --claude-hook-log) export CLAUDE_HOOK_LOG="$2"; shift 2 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
# a bind-mounted path that does not exist would be created as a directory by Docker; make sure they are files
mkdir -p "$(dirname "$OPENCODE_LOG")"; [ -e "$OPENCODE_LOG" ] || : > "$OPENCODE_LOG"
[ "$CLAUDE_HOOK_LOG" = /dev/null ] || [ -e "$CLAUDE_HOOK_LOG" ] || : > "$CLAUDE_HOOK_LOG"

# the dashboard service from scripts/install.sh would fight for port 8765
if systemctl --user is-active logsum-stats.service >/dev/null 2>&1; then
  systemctl --user disable --now logsum-stats.service; echo "stopped systemd logsum-stats.service (the container serves the dashboard now)"
fi

cd "$REPO"
export COMPOSE_BAKE=false   # plain builder; buildx/bake is not needed and often not installed
if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
else
  echo "docker compose not found; using plain docker (run scripts/install-compose.sh to get compose)"
  docker build -t logsum:latest logsum
  docker rm -f logsum >/dev/null 2>&1 || true
  docker volume create logsum-data >/dev/null
  docker run -d --name logsum --restart unless-stopped -p "$LOGSUM_BIND:8765:8765" \
    -v logsum-data:/data -v "$OPENCODE_LOG:/inspect/opencode.log:ro" -v "$CLAUDE_HOOK_LOG:/inspect/claude-code.log:ro" logsum:latest
fi

# host command -> service (with local/passthrough fallback)
mkdir -p "$HOME/.local/bin"
sed "s|^LOCAL=.*|LOCAL=\"\${LOGSUM_LOCAL:-$REPO/logsum/logsum.py}\"|" "$REPO/logsum/client/logsum" > "$HOME/.local/bin/logsum"
chmod +x "$HOME/.local/bin/logsum"

for i in $(seq 1 30); do curl -sf http://127.0.0.1:8765/health >/dev/null && break; sleep 1; done
echo "== health: $(curl -s http://127.0.0.1:8765/health)"
echo "== self test:"
python3 "$REPO/scripts/make-sample-log.py" | LOGSUM_AGENT=docker-test "$HOME/.local/bin/logsum" | head -3
echo "dashboard: http://localhost:8765"
