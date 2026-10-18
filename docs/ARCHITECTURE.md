# Architecture

서랍 (Seorap) is a single-user tool. One person pastes one public YouTube URL, chooses an output, and saves the file.

## Processes

- `app` serves the HTTP API and, in the Docker image, the compiled React screen, on the same origin.
- `worker` is a second process of the same image. It holds an exclusive local lock, claims queued jobs, and owns the yt-dlp/FFmpeg process group.
- The browser never talks to yt-dlp. Analysis and downloads run in a bounded subprocess. Progress is NDJSON, not scraped console text.
- This preview host has to serve the screen through the workspace's Vite application on port 8080. That process proxies `/api` and `/healthz` to the API. The reference deployment does not use that proxy: FastAPI serves `backend/app/static`.

## Format policy

Compatible MP4 means verified H.264, 8-bit 4:2:0 SDR video and AAC audio, copied when the source already matches. A different codec, pixel format, or color conversion is not labeled compatible. Conversion to that profile is off unless `ENABLE_TRANSCODING=true` and the job carries explicit consent. HDR or 10-bit input is rejected rather than quietly recolored.

MP3 is a real encode at 128, 192, or 320 kbps with libmp3lame. A higher output bitrate does not invent detail. Original audio copies the selected platform stream into a matching container (AAC as M4A, Opus as WebM). It is not the uploader's master.

An accepted job stores the output contract. At execution the worker resolves fresh streams. If the same contract cannot be met, the job fails with `FORMAT_CHANGED` and does not downgrade.

## Jobs

Status, phase, cancellation, and file state are separate. Creating a job returns 202. The API process does not download media. Cancellation signals the worker, which terminates the child process group. A crash marks an abandoned running job interrupted only after the new worker owns the lock.

## Privacy and the network boundary

One password, stored as scrypt. Sessions are HttpOnly cookies. State-changing requests need the CSRF header, a matching Origin, and an allowed Host. The reference Compose file publishes `127.0.0.1:8000` only.

The URL allowlist reduces what the app asks the engine to open. It does not prove that every yt-dlp CDN request is confined. Remote or public hosting is unsupported. A VPN reaches the page; it does not make outbound media requests safe.

Thumbnails are fetched by a narrow server-side request. Titles are rendered as text.

## Storage

SQLite uses WAL on the local volume (`/data/state`). Finished files live under `/data/files`. Staging stays on the same filesystem so publication can be atomic. Unretained files expire after 24 hours. Kept files count toward the quota and are not deleted to free space.
