#!/usr/bin/env bash
# Copy the logsum plugin into OpenCode's global plugin directory.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.config/opencode/plugins"
cp "$REPO/opencode/logsum.js" "$HOME/.config/opencode/plugins/logsum.js"
echo "installed $HOME/.config/opencode/plugins/logsum.js (loaded at next OpenCode start)"
echo "audit log: $HOME/.config/opencode/logsum-plugin.log"
