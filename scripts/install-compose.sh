#!/usr/bin/env bash
# Install the Docker Compose v2 CLI plugin for the current user (no sudo). Skips if `docker compose` already works.
set -euo pipefail
if docker compose version >/dev/null 2>&1; then docker compose version; exit 0; fi
VER="${COMPOSE_VERSION:-v2.40.0}"
ARCH=$(uname -m); case "$ARCH" in x86_64) A=x86_64 ;; aarch64|arm64) A=aarch64 ;; *) echo "unsupported arch $ARCH"; exit 1 ;; esac
mkdir -p "$HOME/.docker/cli-plugins"
curl -fsSL "https://github.com/docker/compose/releases/download/$VER/docker-compose-linux-$A" -o "$HOME/.docker/cli-plugins/docker-compose"
chmod +x "$HOME/.docker/cli-plugins/docker-compose"
docker compose version
