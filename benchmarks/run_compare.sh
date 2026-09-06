#!/usr/bin/env bash
# Regenerate the tool-output corpus (raw + RTK) and run the RTK vs Tamp comparison, all inside WSL.
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export TAMP_JS="$(npm root -g)/@sliday/tamp/bin/tamp.js"
tr -d '\r' < /mnt/c/claude/lingua-bench/gen_corpus.sh > ~/gen_corpus.sh
bash ~/gen_corpus.sh 2>&1 | grep -E '^\[' | paste - - | column -t -s $'\t' 2>/dev/null || true
echo "=== compare ==="
cd "$HOME/lingua-bench"
uv run --with requests python /mnt/c/claude/lingua-bench/compare.py 2>&1 | grep -vE 'Warning|warn|^\s*$'
