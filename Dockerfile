# Local reference image. Do not auto-update yt-dlp in a running container.
# Rebuild, retest, and keep the previous tag when upgrading yt-dlp and yt-dlp-ejs together.

FROM node:22-bookworm-slim AS ui
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend ./frontend
COPY src/styles.css ./src/styles.css
COPY src/features/downloads ./src/features/downloads
RUN npx vite build --config frontend/vite.config.ts

FROM python:3.12-slim-bookworm AS runtime
ARG DENO_VERSION=2.9.7
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg unzip \
  && rm -rf /var/lib/apt/lists/* \
  && ffmpeg -hide_banner -encoders | grep -q libx264 \
  && ffmpeg -hide_banner -encoders | grep -q aac \
  && ffmpeg -hide_banner -encoders | grep -q libmp3lame \
  && mkdir -p /opt/seorap/bin \
  && curl -fsSL -o /tmp/deno.zip "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" \
  && unzip -q /tmp/deno.zip -d /opt/seorap/bin \
  && chmod 755 /opt/seorap/bin/deno \
  && rm /tmp/deno.zip \
  && useradd --uid 10001 --home-dir /opt/seorap --shell /usr/sbin/nologin seorap

WORKDIR /opt/seorap
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
  && pip install --no-cache-dir "yt-dlp-ejs==0.8.0"
COPY backend /opt/seorap
COPY --from=ui /src/backend/app/static /opt/seorap/app/static
RUN mkdir -p /data/state /data/tmp /data/files /data/logs \
  && chown -R 10001:10001 /opt/seorap /data

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/opt/seorap \
  DATA_DIR=/data \
  PATH="/opt/seorap/bin:${PATH}" \
  FFMPEG_PATH=/usr/bin/ffmpeg \
  FFPROBE_PATH=/usr/bin/ffprobe \
  DENO_PATH=/opt/seorap/bin/deno \
  LOCAL_HTTP=1 \
  MEDIA_ADAPTER=ytdlp

USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
