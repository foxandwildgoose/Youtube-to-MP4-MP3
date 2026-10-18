# 서랍

A personal, single-user tool that turns one public YouTube URL into one MP4 or MP3 file and keeps it on this machine.

Download only material you are allowed to download and use. Copyright and YouTube's terms are separate questions from whether a file is technically reachable. Private or noncommercial use does not by itself grant permission. YouTube Premium offline viewing is not an MP4/MP3 export feature. For your own uploads, use YouTube Studio or Google Takeout.

- [YouTube terms](https://www.youtube.com/static?template=terms)
- [Download your own uploads](https://support.google.com/youtube/answer/56100?hl=en)

The screen defaults to Korean. The language control switches it to English. Source titles stay in their original language.

## What it does

Paste a watch, youtu.be, Shorts, or matching music/mobile link. A watch URL that also carries a playlist parameter processes only that video. A timestamp is ignored; clipping is not in this version. Channels, search pages, pure playlists, live and upcoming streams, login-only videos, members-only videos, and DRM are rejected with a specific reason.

Outputs:

- Compatible MP4: H.264, 8-bit 4:2:0 SDR, AAC when the source has audio. Streams that already match are copied. Portrait dimensions are kept.
- MP3: 128, 192, or 320 kbps. The default is 192. A higher bitrate cannot restore missing detail.
- Original audio: the platform stream, copied. AAC becomes M4A. Opus stays in WebM. This is not the uploader's master file.

"Create a new file" always rechecks the source. "Download to this device" saves the file the server already has. The browser chooses the folder on your computer.

## Reference deployment

Docker Compose on one computer. The API and the worker share an image. SQLite and media sit on a named local volume. Only `127.0.0.1:8000` is published. This is not a public service, and this repository does not deploy one.

The preview shell in this workspace is a separate Vite host required by that environment. It proxies the API. It is not the Compose runtime. If that API is down, the screen says **Backend not connected** and does not pretend a download succeeded.

### Defaults

| Setting | Default |
| --- | --- |
| Media concurrency | 1 |
| Analysis concurrency | 1 |
| Waiting jobs | 20 |
| Analysis TTL / deadline | 10 minutes / 60 seconds |
| Maximum source duration | 4 hours |
| Native MP4 cap / default selection | 2160p / up to 1080p |
| Conversion cap | 1080p SDR, and only when enabled |
| MP3 default | 192 kbps |
| Input and final file | 5 GiB each |
| Job workspace | 12 GiB |
| Managed storage | 50 GiB |
| Minimum free space | 2 GiB |
| Active job deadline | 2 hours, not counting queue time |
| Unretained files | 24 hours |
| Ordinary history | 90 days; kept-file records remain |
| Automatic retries | at most 2 extra attempts |
| Playlists | off; first 20 entries when enabled |
| Video conversion | off until you enable it |

These are product limits, not YouTube's limits. A 4-hour source can still miss the 2-hour processing deadline. Leave several gigabytes free beyond the file you expect. Estimates are not filesystem quotas.

### Linux and macOS

```sh
cp .env.example .env
sh scripts/setup.sh
docker compose exec -it app python -m app.cli bootstrap
```

Open `http://127.0.0.1:8000`.

### Windows PowerShell

```powershell
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
docker compose exec -it app python -m app.cli bootstrap
```

To show finished files in a chosen Windows folder, replace the named volume on both services with a bind mount such as `C:\Seorap\library:/data`. Inside the container the library is `/data/files`. The host folder's permissions must allow user id 10001. Do not put the SQLite directory on a network share.

### Password

`python -m app.cli bootstrap` reads the password without echoing it and stores a scrypt hash. `reset-password` replaces it and revokes sessions. `ALLOW_HTTP_BOOTSTRAP` stays `0` in `.env.example`. The preview process in this workspace sets it to `1` only so a person without a shell can set the first password from loopback. That is not the Compose default.

### Everyday commands

```sh
docker compose up -d
docker compose stop
docker compose start
docker compose exec app python -m app.cli reset-password
```

Stopping the containers does not delete the volume. Deleting the volume deletes the password, history, and files. Do not do that as part of an update.

Authenticated diagnostics are at `GET /api/v1/diagnostics` after you sign in (the Diagnostics control). `GET /healthz` only says the process is up. A healthy process does not mean YouTube can be reached.

### Backup and restore

Quiesce the worker, then use the SQLite backup API from inside the app container:

```sh
docker compose stop worker
docker compose exec -T app python -c "import sqlite3; s=sqlite3.connect('/data/state/app.db'); t=sqlite3.connect('/data/state/app.db.bak'); s.backup(t); t.close(); s.close()"
docker compose start worker
```

From a checkout, with `DATA_DIR` pointing at the volume:

```sh
DATA_DIR=/path/to/volume python scripts/backup.py /path/to/app.db.bak
```

Restore by stopping both services, replacing `state/app.db` (and removing leftover `-wal` and `-shm` files) with the backup, then starting again.

### Upgrade and rollback

Pin `yt-dlp` and `yt-dlp-ejs` together in `backend/requirements.txt`. Rebuild, run `pytest`, and keep the previous image tag (`docker image tag seorap:local seorap:previous` before building). Roll back with `docker compose up -d` after tagging `previous` back to `seorap:local`. Do not auto-update inside a running container. The volume is kept across a normal recreate.

## Configuration

Copy `.env.example`. High-risk limits and paths stay there. The settings screen only stores language, theme, and the preferred MP3 rate.

`ENABLE_PLAYLISTS=true` allows inspection of the first 20 positions and no more. Nothing is selected for you. Each chosen video is analyzed on its own.

`ENABLE_TRANSCODING=true` allows an explicit "convert to compatible MP4" choice for supported SDR. The screen asks for consent and warns that conversion takes longer and can lose quality.

`MEDIA_ADAPTER=fixture` is for tests. Production must stay on `ytdlp`.

## Layout

| Path | Role |
| --- | --- |
| `backend/app` | API, worker, engine, planner, storage |
| `src/features/downloads` | The screen, shared by the preview and the static build |
| `frontend/` | Vite entry that FastAPI serves |
| `data/` in this checkout, `/data` in Compose | `state/`, `tmp/`, `files/`, `logs/` |
| `docs/ARCHITECTURE.md` | Worker, formats, and the local network boundary |
| `docs/VERIFICATION.md` | Commands that were actually run |

Logical folder shown in the screen: Library (`/data/files` on the server).

## Failure diagnosis

The API returns `{ "error": { "code", "message", "retryable", "action" } }`. `SOURCE_AUTH_REQUIRED` is not the same as a bad URL. `SOURCE_RATE_LIMITED` waits out a cooldown before the next probe. `FORMAT_CHANGED` means analyze again. `FILE_EXPIRED`, `FILE_MISSING`, and a deleted file are different states.

A 403 is not retried forever. One metadata refresh is allowed inside a shared budget of three attempts total. There is no cookie import, proxy rotation, or CAPTCHA handling.

## Tests

```sh
cd backend && python -m pytest
```

That suite uses short FFmpeg fixtures. It does not contact YouTube. An authorized live check is separate:

```sh
cd backend && LIVE_TEST_URL='https://www.youtube.com/watch?v=YOUR_PERMITTED_VIDEO' python -m pytest tests/test_live_smoke.py -rs
```

Without `LIVE_TEST_URL` that test is skipped. A skipped live test is not a pass against YouTube.

## Third-party notices

Components are separately licensed. Do not treat them as one license.

- yt-dlp 2026.8.19 — Unlicense
- yt-dlp-ejs 0.8.0 — see the package metadata
- Deno 2.9.7 — MIT
- FFmpeg — the static build used in this workspace is GPL (libx264, libmp3lame). The Debian `ffmpeg` package used by the image has its own licensing; check `ffmpeg -version` and the distro copyright file
- FastAPI, Starlette, Uvicorn, Pydantic — MIT
- React — MIT

This project does not copy Cobalt or MeTube source. Those products are interface references only.

## Network boundary

The supported deployment is an authenticated loopback service. Publishing it on a public interface, or assuming an input allowlist blocks every outbound CDN request, is unsupported. A VPN only changes who can open the page.
