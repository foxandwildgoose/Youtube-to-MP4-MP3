#!/bin/sh
# Revive contract: bring the preview and the local media API back.
# Idempotent. Exits 0 when both are already answering.
set -eu
cd /workspace

export DATA_DIR="${DATA_DIR:-/workspace/data}"
export LOCAL_HTTP=1
export ALLOW_HTTP_BOOTSTRAP=1
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost}"
export FFMPEG_PATH="${FFMPEG_PATH:-/usr/local/bin/ffmpeg}"
export FFPROBE_PATH="${FFPROBE_PATH:-/workspace/bin/ffprobe}"
export DENO_PATH="${DENO_PATH:-/workspace/bin/deno}"
export PATH="/workspace/bin:${PATH}"
export PYTHONPATH="/workspace/backend${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
export MEDIA_ADAPTER="${MEDIA_ADAPTER:-ytdlp}"
export ENABLE_PLAYLISTS="${ENABLE_PLAYLISTS:-0}"
export ENABLE_TRANSCODING="${ENABLE_TRANSCODING:-0}"

mkdir -p "$DATA_DIR/state" "$DATA_DIR/tmp" "$DATA_DIR/files" "$DATA_DIR/logs"

if ! curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8000/healthz; then
  python3 -m uvicorn app.main:app --app-dir /workspace/backend --host 127.0.0.1 --port 8000 >>"$DATA_DIR/logs/api.log" 2>&1 &
  python3 -m app.worker >>"$DATA_DIR/logs/worker.log" 2>&1 &
  i=0
  while [ "$i" -lt 40 ]; do
    if curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8000/healthz; then
      break
    fi
    i=$((i + 1))
    sleep 0.25
  done
  if ! curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8000/healthz; then
    echo "media API did not start" >&2
    exit 1
  fi
fi

if curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8080/; then
  exit 0
fi

npm run dev >>"$DATA_DIR/logs/web.log" 2>&1 &
i=0
while [ "$i" -lt 60 ]; do
  if curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8080/; then
    exit 0
  fi
  i=$((i + 1))
  sleep 0.25
done
echo "preview did not start" >&2
exit 1
