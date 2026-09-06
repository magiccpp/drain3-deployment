#!/usr/bin/env bash
# Set up an isolated uv project for LLMLingua-2 in WSL home (native ext4, not /mnt/c).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
PROJ="$HOME/lingua-bench"

mkdir -p "$PROJ" && cd "$PROJ"
if [ ! -f pyproject.toml ]; then
  uv init --bare --python 3.12 --name lingua-bench
fi
# torch from the CUDA 12.6 index (matches the working torch in gputest-venv), rest from PyPI.
uv add --index pytorch-cu126=https://download.pytorch.org/whl/cu126 torch
uv add llmlingua tiktoken requests
uv run python - <<'EOF'
import torch, transformers, llmlingua, tiktoken
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.version.cuda)
print("gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
print("transformers", transformers.__version__)
EOF
echo SETUP-DONE
