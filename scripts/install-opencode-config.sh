#!/usr/bin/env bash
# Install the OpenCode model configuration (Terra main, Luna for subagents and log checks).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.config/opencode"
DST="$HOME/.config/opencode/opencode.jsonc"
if [ -f "$DST" ] && ! cmp -s "$DST" "$REPO/opencode/opencode.jsonc"; then
  cp "$DST" "$DST.before-logsum"; echo "backed up existing config to $DST.before-logsum"
fi
cp "$REPO/opencode/opencode.jsonc" "$DST"
echo "installed $DST"
export PATH="$HOME/.opencode/bin:$PATH"
opencode agent list 2>/dev/null | grep -E '^\S+ \((primary|subagent|all)\)' || true
