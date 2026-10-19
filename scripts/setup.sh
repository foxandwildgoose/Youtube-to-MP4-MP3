#!/bin/sh
# Linux/macOS setup for the authenticated loopback Docker profile.
set -eu
cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is missing. Install Docker Engine/Desktop and Compose v2." >&2
  exit 1
fi
docker compose version >/dev/null || { echo 'Docker Compose v2 is unavailable.' >&2; exit 1; }
docker info >/dev/null || { echo 'Docker daemon is unavailable. Start Docker Engine/Desktop.' >&2; exit 1; }
if [ ! -f .env ]; then
  if [ ! -f .env.example ]; then
    echo 'Missing .env.example; restore the source template before setup.' >&2
    exit 1
  fi
  (umask 077; cp .env.example .env)
  echo 'Created .env from .env.example; existing configurations are preserved.'
fi
# Explicit override for nested cloud Docker only; ordinary local setup has no CA mounts.
if [ -n "${CODEX_PROXY_CERT:-}" ]; then
  export BUILDX_CONFIG="${BUILDX_CONFIG:-$PWD/.cache/buildx}"
  set -- -f docker-compose.yml -f docker-compose.cloud.yml
else
  set -- -f docker-compose.yml
fi
docker compose "$@" config --quiet
docker compose "$@" build
docker compose "$@" up -d --wait --wait-timeout 90
printf '%s\n' 'Ready: http://127.0.0.1:8000' 'Initialize the password interactively:' '  docker compose exec app python -m app.cli bootstrap'
