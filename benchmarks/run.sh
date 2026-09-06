#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export TOKENIZERS_PARALLELISM=true
cd "$HOME/lingua-bench"
uv run python /mnt/c/claude/lingua-bench/bench.py 2>&1 | grep -vE 'Warning|warn|^\s*$'
