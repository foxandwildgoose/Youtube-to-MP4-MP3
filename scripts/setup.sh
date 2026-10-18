#!/bin/sh
# Linux/macOS operator setup for the loopback Docker deployment.
set -eu
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Wrote .env from .env.example. Review the limits before large jobs."
fi

docker compose build
docker compose up -d
echo "Open http://127.0.0.1:8000"
echo "Set the password in a terminal, not in the browser, when ALLOW_HTTP_BOOTSTRAP=0:"
echo "  docker compose exec -it app python -m app.cli bootstrap"
