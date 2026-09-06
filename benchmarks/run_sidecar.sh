#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/lingua-bench"
cp /mnt/c/claude/lingua-bench/sidecar_gpu.py ./sidecar_gpu.py
exec uv run --with fastapi --with uvicorn uvicorn sidecar_gpu:app --host 0.0.0.0 --port 8788
