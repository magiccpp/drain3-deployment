#!/usr/bin/env bash
# End-to-end test: OpenCode reads a 300-line log through bash; the plugin must hand the model a Drain3 summary.
#   scripts/test-opencode.sh [provider/model]     (needs a provider key in env or `opencode auth login`)
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"
MODEL="${1:-anthropic/claude-haiku-4-5}"
"$REPO/scripts/install-opencode-plugin.sh"
: > "$HOME/.config/opencode/logsum-plugin.log"

rm -rf "$HOME/oc-test" && mkdir -p "$HOME/oc-test" && cd "$HOME/oc-test"
python3 "$REPO/scripts/make-sample-log.py" > app.log
git init -q . 2>/dev/null || true

echo "=== opencode run (headless, $MODEL) ==="
opencode run --auto -m "$MODEL" \
  "Use the bash tool to run exactly this command: tail -n 300 app.log   Then answer in 3 short bullet points: which error/warning patterns appear and how often."
echo "--- plugin audit log:"; cat "$HOME/.config/opencode/logsum-plugin.log"
SID=$(opencode session list 2>/dev/null | grep -oE 'ses_[A-Za-z0-9]+' | head -1)
if [ -n "$SID" ]; then
  echo "--- summary header in the session (proves the model received it):"
  opencode export "$SID" 2>/dev/null | grep -oE '\[logsum\] [0-9]+ lines -> [0-9]+ templates' | head -1
fi
