#!/bin/sh
# Grok preview/revive profile. Personal operation opens without a password.
set -eu
seorap_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$seorap_root"
if [ -x "$seorap_root/.venv/bin/python" ]; then
  exec "$seorap_root/.venv/bin/python" "$seorap_root/scripts/preview-runtime.py"
fi
exec python3 "$seorap_root/scripts/preview-runtime.py"
