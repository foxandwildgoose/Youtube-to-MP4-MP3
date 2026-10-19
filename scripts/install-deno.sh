#!/bin/sh
# Official pinned Linux amd64 runtime. Never accept an unverified executable.
set -eu
deno_arch="${TARGETARCH:-$(uname -m)}"
case "$deno_arch" in
  amd64|x86_64) ;;
  *) echo "Unsupported Deno platform: $deno_arch. This release supports linux/amd64; use explicit Docker amd64 emulation on ARM." >&2; exit 2 ;;
esac
deno_dest="${1:-/opt/seorap/bin}"
deno_version=2.9.7
# https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-unknown-linux-gnu.zip.sha256sum
deno_sha256=c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490
deno_tmp="$(mktemp -d)"
trap 'rm -rf "$deno_tmp"' EXIT HUP INT TERM
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 180 \
  "https://github.com/denoland/deno/releases/download/v${deno_version}/deno-x86_64-unknown-linux-gnu.zip" \
  --output "$deno_tmp/deno.zip"
printf '%s  %s\n' "$deno_sha256" "$deno_tmp/deno.zip" | sha256sum --check --status
mkdir -p "$deno_dest"
unzip -q "$deno_tmp/deno.zip" -d "$deno_tmp/extracted"
install -m 0755 "$deno_tmp/extracted/deno" "$deno_dest/deno"
"$deno_dest/deno" --version
