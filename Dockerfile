# syntax=docker/dockerfile:1
# Native linux/amd64 only. ARM hosts must explicitly select amd64 emulation.
# Rebuild and rerun fixture gates when upgrading yt-dlp/EJS/verified Deno together.
FROM node:22-bookworm-slim AS ui
WORKDIR /src
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm install --global --strict-ssl=true npm@11.9.0 && npm ci --strict-ssl=true
# One source-copy layer also keeps Docker's vfs storage bounded in cloud builds.
COPY . .
RUN npm run build:spa

FROM python:3.12-slim-bookworm AS base
ARG TARGETARCH
WORKDIR /opt/seorap
COPY backend/requirements.txt /tmp/requirements.txt
COPY scripts/install-deno.sh scripts/init-volume.sh /opt/seorap/
RUN --mount=type=secret,id=proxy_bundle \
    set -eu; \
    test "$TARGETARCH" = amd64 || { echo 'Only linux/amd64 is supported; select --platform linux/amd64.' >&2; exit 2; }; \
    if [ -f /run/secrets/proxy_bundle ]; then export CURL_CA_BUNDLE=/run/secrets/proxy_bundle PIP_CERT=/run/secrets/proxy_bundle; fi; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg unzip \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -hide_banner -encoders | grep -q libx264 \
    && ffmpeg -hide_banner -encoders | grep -q aac \
    && ffmpeg -hide_banner -encoders | grep -q libmp3lame \
    && sh /opt/seorap/install-deno.sh /opt/seorap/bin \
    && rm /opt/seorap/install-deno.sh \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && useradd --uid 10001 --home-dir /opt/seorap --shell /usr/sbin/nologin seorap \
    && install -d -o 10001 -g 10001 /data /data/state /data/tmp /data/files /data/logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/seorap \
    DATA_DIR=/data \
    PATH="/opt/seorap/bin:${PATH}" \
    FFMPEG_PATH=/usr/bin/ffmpeg \
    FFPROBE_PATH=/usr/bin/ffprobe \
    DENO_PATH=/opt/seorap/bin/deno \
    DENO_DIR=/tmp/deno-cache \
    XDG_CACHE_HOME=/tmp/cache \
    LOCAL_HTTP=1 \
    REQUIRE_PASSWORD=1 \
    ALLOW_HTTP_BOOTSTRAP=0 \
    MEDIA_ADAPTER=ytdlp

# Test dependencies/fixtures never enter the production image.
FROM base AS test
COPY --chown=10001:10001 backend /opt/seorap
RUN --mount=type=secret,id=proxy_bundle \
    if [ -f /run/secrets/proxy_bundle ]; then export PIP_CERT=/run/secrets/proxy_bundle; fi; \
    pip install --no-cache-dir -r /opt/seorap/requirements-test.txt
USER 10001:10001
ENV DATA_DIR=/tmp/seorap-test-state
CMD ["python", "-m", "pytest", "-ra", "-p", "no:cacheprovider"]

FROM base AS runtime
# Explicit ownership also supports source checkouts created with umask 077.
COPY --chown=10001:10001 backend/app /opt/seorap/app
COPY --from=ui --chown=10001:10001 /src/backend/app/static /opt/seorap/app/static
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
