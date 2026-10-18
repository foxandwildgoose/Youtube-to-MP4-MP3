# Implementation checklist

1. Foundation — FastAPI, worker, SQLite migrations, password sessions, diagnostics, Compose, and the preview shell. Done.
2. Single-source engine — URL policy, analysis, MP4/MP3/original-audio planning, FFmpeg, ffprobe. Done. Covered by local fixtures.
3. Durable jobs — claims, idempotency, subprocess groups, progress, SSE, cancellation, restart reconciliation. Done.
4. Files and UI — range responses, retention, Korean/English UI, light/dark/system, history. Done.
5. Optional flags — `ENABLE_TRANSCODING` and `ENABLE_PLAYLISTS` default off. Enabled behavior is implemented and tested. Done.
6. Delivery checks — pytest without YouTube, SPA build, preview. Live YouTube smoke stays opt-in via `LIVE_TEST_URL`.
