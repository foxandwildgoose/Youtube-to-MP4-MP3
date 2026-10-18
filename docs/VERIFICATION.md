# Verification report

Date: 2026-10-18. Host tools: Python 3.10.22, Node 22, FFmpeg 7.0.2-static (libx264, aac, libmp3lame), ffprobe 7.0.2-static, Deno 2.9.7, yt-dlp 2026.8.19, yt-dlp-ejs 0.8.0, FastAPI 0.143.5.

## Commands actually run

| Command | Result |
| --- | --- |
| `python3 -m pip install -r backend/requirements.txt` | Installed the pinned set |
| `cd backend && python3 -m pytest -q` | 30 passed, 1 skipped |
| `npm run typecheck` | Passed |
| `npm run build` | Passed (TanStack/Nitro preview bundle) |
| `npm run build:spa` | Passed. Static files in `backend/app/static` |
| `node scripts/browser-smoke.mjs` against the dev screen | Passed. Korean setup screen, no console errors, no horizontal overflow at 1280 and 390 |
| Built-screen smoke after the API bridge | Passed. No console errors. Desktop text length differed from the first dev capture; the screen is the same password form |
| `docker version` | Not available in this environment. Image was not built here |

## T16

`tests/test_live_smoke.py` skipped: `LIVE_TEST_URL` was not set. Local FFmpeg fixtures do not prove that YouTube is reachable today.

## What was exercised

Local fixtures, not YouTube, cover URL rejection, H.264/AAC and portrait caps, VP9 not labeled as H.264, disabled and consented conversion, HDR rejection, MP3 bitrates, original audio, analysis expiry, idempotency, cancellation, invalid output, byte ranges, retention, worker restart, CSRF/path checks, 403 refresh budget, 429 cooldown, and the disabled/enabled playlist cap.

The dev screen is connected to the local API and worker. Diagnostics require a signed-in session. `GET /healthz` does not contact YouTube.

## Not claimed

- The Docker image was not built or started here.
- No live YouTube download was performed.
- Public hosting and full SSRF confinement of yt-dlp's own CDN requests are unsupported.
- A healthy local process is not proof that every YouTube URL can be saved.

## Requirement map

| IDs | Where |
| --- | --- |
| R01–R02, R36 | This report, `README.md`, `IMPLEMENTATION_CHECKLIST.md` |
| R03–R04, R12 | `backend/app/services/url_policy.py`, `analysis.py`, README notice |
| R05, R20, R31 | `backend/requirements.txt`, `Dockerfile`, `backend/app/diagnostics.py` |
| R06–R11, R34 | `backend/app/services/format_planner.py`, `engine/child.py`, `media_validate.py` |
| R13–R18 | `backend/app/worker.py`, `engine_runner.py` |
| R15–R16 | `backend/app/main.py` SSE and `src/features/downloads/app.tsx` |
| R21–R24, R27 | `backend/app/services/storage.py`, file route in `main.py` |
| R19 | `backend/app/errors.py` |
| R25–R29, R32 | `backend/app/security.py`, `safe_http.py` |
| R30 | `docker-compose.yml`, `scripts/setup.sh`, `scripts/setup.ps1` |
| R33 | `src/features/downloads` |
| R35, T01–T15 | `backend/tests/` |
| T16 | `backend/tests/test_live_smoke.py` (skipped) |
