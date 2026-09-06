#!/usr/bin/env bash
# Install logsum (Drain3 summarizer) + the stats dashboard on Ubuntu / WSL2. No sudo needed.
#   scripts/install.sh [--claude-hook-log /mnt/c/Users/<you>/.claude/hooks/logsum-hook.log] [--bind 0.0.0.0]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIND="127.0.0.1"; CLAUDE_LOG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --claude-hook-log) CLAUDE_LOG="$2"; shift 2 ;;
    --bind) BIND="$2"; shift 2 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

echo "== python env"
( cd "$REPO/logsum" && uv sync -q )

echo "== wrappers in ~/.local/bin"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/logsum"
cat > "$HOME/.local/bin/logsum" <<EOF
#!/usr/bin/env bash
exec "$REPO/logsum/.venv/bin/python" "$REPO/logsum/logsum.py" "\$@"
EOF
cat > "$HOME/.local/bin/logsum-stats" <<EOF
#!/usr/bin/env bash
exec "$REPO/logsum/.venv/bin/python" "$REPO/logsum/logsum_stats.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/logsum" "$HOME/.local/bin/logsum-stats"

echo "== dashboard service (systemd --user)"
LOGS="$HOME/.config/opencode/logsum-plugin.log"
[ -n "$CLAUDE_LOG" ] && LOGS="$CLAUDE_LOG:$LOGS"
mkdir -p "$HOME/.config/systemd/user"
sed -e "s|^Environment=LOGSUM_INSPECT_LOGS=.*|Environment=LOGSUM_INSPECT_LOGS=$LOGS|" \
    -e "s|--host 127.0.0.1|--host $BIND|" "$REPO/logsum/logsum-stats.service" > "$HOME/.config/systemd/user/logsum-stats.service"
if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable --now logsum-stats.service
  systemctl --user restart logsum-stats.service
  loginctl enable-linger "$USER" 2>/dev/null || true
  echo "dashboard: http://localhost:8765  (bound to $BIND)"
else
  echo "systemd --user not available; start manually:  nohup logsum-stats --host $BIND --port 8765 &"
fi

echo "== self test"
printf 'a\nb\nc\n' | logsum | wc -l | xargs echo "passthrough lines (expect 3):"
python3 "$REPO/scripts/make-sample-log.py" > /tmp/logsum-sample.log
LOGSUM_AGENT=install-test logsum < /tmp/logsum-sample.log | head -3
echo "done. Next: scripts/install-opencode-plugin.sh, and on Windows claude-code\\install.ps1"
