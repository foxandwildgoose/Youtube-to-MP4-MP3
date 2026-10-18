# Personal YouTube to MP4 and MP3 Downloader Build Specification

Version: 1.0  
Research baseline: 2026-10-18, Asia/Seoul  
Prompt language: English  
Default product language: Korean, with an English language switch

## 0. Execution contract and outcome [R01 R02 R36]

Act as a senior full-stack engineer. Implement a complete, working, single-user, self-hosted web application that analyzes a YouTube URL and produces a downloadable MP4 or MP3 file. Use the requirements in this document as the implementation specification. Create and modify actual project files, run the checks available in the environment, fix failures, and provide reproducible startup instructions. Do not stop after producing a plan, a design mockup, a file tree, or disconnected snippets.

Before coding, inspect the existing project, repository instructions, available runtimes, package manager, and deployment environment. Preserve unrelated work. Identify whether this particular Build environment supports Python, subprocesses, FFmpeg/ffprobe, the JavaScript runtime needed by yt-dlp, long-running workers, persistent local storage, outbound media requests, and streaming responses. A product being called “Build” does not establish these capabilities. Do not assume a particular Build vendor, or assume every Build product is frontend-only.

The supported reference deployment is Docker Compose on one host with persistent local volumes. It must remain fully usable without a Build subscription at runtime. If the current preview cannot execute the backend, still generate the complete backend and deployment files, run all feasible local checks, and show a clear “Backend not connected” state in the preview. A separately enabled demo may use deterministic fixtures and must display “Demo data”; production endpoints must never return simulated metadata, progress, or successful downloads. Distinguish implemented, tested locally, tested against YouTube, and blocked by the environment in the final report. Do not expose or deploy a public service automatically.

Use a single reference stack:

- React, TypeScript, Vite, and Tailwind CSS for the frontend.
- Python and FastAPI for the API and serving the compiled SPA from the same origin.
- One dedicated Python worker process in a separate Compose service, using the same application image.
- SQLite on a local persistent Docker volume, with WAL, short transactions, migrations, and a busy timeout.
- yt-dlp, compatible yt-dlp-ejs, a supported JavaScript runtime, FFmpeg, and ffprobe.
- REST for commands and snapshots; Server-Sent Events for progress.

Do not add an alternative Next.js or Node backend, Redis, Celery, a paid database, an LLM API, or a YouTube Data API key requirement to this baseline. If an existing repository makes a stack change necessary, explain the concrete reason and preserve the behavior and acceptance criteria below.

## 1. Product scope and permitted use [R03 R04 R12]

The primary workflow is one user pasting one public, accessible YouTube video URL, selecting an output, waiting for processing, and saving the resulting file. Support validated watch links, youtu.be links, Shorts links, and supported mobile/music host variants that identify a video. A watch URL containing a playlist parameter processes only that video by default. Ignore timestamp parameters for full-video downloads and state this in the UI; clipping is outside v1.

The single-video endpoint must reject pure playlists, channels, search URLs, active live streams, upcoming streams, unsupported schemes, and unsupported sites. Reject content requiring login or restricted access, paid/member-only content, and DRM-protected media with an accurate reason. A completed livestream may be treated as a video only when the extractor reports an available, finite, non-live recording that satisfies normal limits.

Implement bounded playlist selection as an optional feature behind `ENABLE_PLAYLISTS=false`. When enabled, a separate playlist endpoint may inspect at most the first 20 source positions, including inaccessible entries, and show that the list is limited. Stop enumeration at that boundary; do not fetch the entire playlist first or scan later entries to replace inaccessible ones. An upstream page may contain extra entries, but the app must not process them or continue pagination beyond the cap. Do not select entries automatically. Analyze each selected entry before it becomes a normal, independently cancellable job; show its actual supported formats, duration, and eligibility. Do not apply one video's opaque choice ID to other entries. Enforce the global queue and rate limits across the batch. Skip inaccessible entries with visible reasons. Do not add ZIP bundling, whole-channel downloads, subscriptions, schedules, or unattended collection.

Other platforms are future extensions. Keep the extractor adapter replaceable, but do not enable the generic extractor or advertise multi-platform support in v1. Do not create nonfunctional controls for future features.

Provide the compact, non-blocking notice requested for this personal tool: users should download only material they are permitted to download and use, and should respect copyright and platform terms. Do not claim that private or noncommercial use alone grants permission. Explain in the README that content rights and the platform's permitted download methods are separate considerations. Link to YouTube's terms and to Studio/Takeout for the user's own uploads. Do not claim Premium offline viewing is a general MP4/MP3 export feature.

Do not implement DRM removal, browser-cookie harvesting, credential capture, login bypass, proxy rotation, CAPTCHA automation, account switching, or automatic evasion recipes after an access failure. Normal support for the verified upstream yt-dlp/EJS components is part of the engine installation, not a promise to defeat access restrictions.

## 2. User experience [R21 R24 R29 R33]

Use Cobalt as inspiration for a restrained, distraction-free interface and MeTube as a reference for download management. Implement original UI code and the application's own yt-dlp backend; do not depend on a public Cobalt instance, an undocumented downloader API, or scraped third-party converter pages.

Keep the main screen simple:

1. A prominent URL field and an Analyze button. Enter submits; invalid input receives a nearby explanation. Clipboard access occurs only after a user action and has a normal paste fallback.
2. A metadata card with title, channel, duration, thumbnail or placeholder, and the canonical source link.
3. Three output tabs: Compatible MP4, MP3, and Original audio. Show only valid options for the analyzed source. Display resolution, actual dimensions for portrait video, codec, frame rate, audio language, and estimated size when known. Keep technical details in a secondary disclosure.
4. A concise confirmation of the selected output and whether conversion is required. The main action is “Create file”. Prevent accidental duplicate submissions without freezing the interface.
5. A job card with phase, truthful progress, speed/ETA when available, queue position, Cancel, and an actionable error or final result.
6. A “Download to this device” button after success. Separately show “Stored on server”, the logical server folder, size, and expiration or retained status. Provide a “Keep on server” option with quota information.

Use Korean as the default UI language and include an English switch through translation keys. Preserve source titles and names in their original language. Keep light, dark, and system themes; use local fonts and assets, responsive layouts, keyboard navigation, visible focus, labels, readable contrast, and restrained screen-reader progress announcements. Verify a narrow mobile viewport and a desktop viewport in both themes. No ads, trackers, external font calls, pop-ups, fake buttons, or autoplay.

History must come from the server. Browser localStorage may store theme/language preferences, but never credentials, signed media URLs, or the authoritative job queue. Distinguish “Download existing file again” from “Create a new file from source”. Missing, expired, and deleted files must have distinct states. Reprocessing performs a fresh analysis and selection; it must not reuse an expired signed media URL. Do not promise that the source or a formerly available format will still exist.

## 3. Engine installation and capabilities [R05 R20 R31]

At implementation time, consult the official yt-dlp installation and EJS documentation and choose supported, compatible versions. The research baseline requires yt-dlp-ejs plus an external supported JavaScript runtime for full YouTube support. Use a verified Deno release by default; do not confuse the Node frontend build stage with a runtime executable installed in the final worker image.

Install FFmpeg and ffprobe executables, not merely a similarly named Python package. Include an FFmpeg build with the MP3 encoder used by this app and the required AAC and optional H.264 encoder. Install the compatible EJS package at image build time; a version-pinned `yt-dlp[default]` dependency set is one valid route. Disable runtime fetching of arbitrary components, plugins, and user configuration. Verify current CLI flags or Python API equivalents against the chosen version rather than inventing option names.

Pin the versions actually resolved and tested in lockfiles, record image/runtime versions and verification dates, and provide a controlled upgrade-and-rollback workflow. Do not auto-update yt-dlp in a running production container. Update yt-dlp and its compatible EJS together, rebuild, run regression checks, and retain the previous image tag. Document applicable third-party licenses for the chosen distributions; do not assume all dependencies or FFmpeg builds have the same license. Do not copy Cobalt or MeTube implementation code without addressing its actual license.

A readiness check must verify database access, writable managed storage, minimum free space, worker heartbeat, yt-dlp/EJS/runtime availability, and required media tools/encoders. Keep simple liveness separate from detailed, authenticated diagnostics. A healthy local process is not proof that YouTube is reachable or that every source can be downloaded. External tests must be explicit, not repeated on each health check.

## 4. URL analysis and output planning [R07 R11 R26 R34]

Parse URLs on the server with a strict, tested policy. Accept only explicit supported YouTube hosts, standard ports, and known video URL shapes. Reject credentials in URLs, control characters, backslashes, ambiguous encoding, unexpected redirects, lookalike domains, IP literals, and non-HTTP(S) schemes. Normalize permitted HTTP inputs to HTTPS without fetching them. Extract a validated video identifier and reconstruct the canonical YouTube watch URL. Do not forward the user's original path/query to the engine. Strip unrelated sharing/tracking parameters. Do not use search or a generic URL fallback.

Analysis is a bounded operation in a subprocess, never blocking the FastAPI event loop. Apply a deadline, result-size limit, and a small global analysis concurrency limit. Share admission control between explicit probes from app and worker services; separate per-process semaphores do not establish a global limit. Release the probe permit before the media-transfer phase. On deadline, terminate the subprocess group. Check extractor result type, source identity, live status, duration, eligibility, and available streams before building an output plan.

Return a sanitized response with an opaque `analysis_id`, canonical source identity, expiration, display metadata, audio tracks, and opaque server-owned `choice_id` values. Each choice includes its semantic output contract and whether it is native-copy or conversion. Unknown fields are `null` or explicitly unavailable; never invent size, bitrate, language, duration, or resolution. A missing thumbnail must not fail an otherwise valid analysis.

Each choice binds output kind, audio-track identity, MP3 target bitrate when applicable, resolved dimensions/frame rate, container/codec policy, and conversion requirement. Changing these UI selections selects the corresponding server-issued choice; do not mix a choice ID with unchecked independent media options.

Do not send raw extractor dictionaries, cookies, headers, filesystem paths, stack traces, or upstream signed download URLs to the browser. Store only the source identity, selected output intent, and the minimal metadata needed for history; do not persist transient signed media URLs. Treat analysis as a short-lived preview, with a default TTL of 10 minutes.

The analysis TTL applies to accepting a new create/retry request. In that transaction, copy the immutable selected output contract into the job record. A previously accepted queued job remains executable after its analysis expires; refresh the source and verify the saved contract at execution instead of expiring the queued job.

At job start, re-extract source information and resolve fresh stream URLs. Validate that the selected resolution, codec policy, audio track, and conversion consent remain satisfiable. Changing an internal format ID is acceptable if the same output contract still holds. If it does not, return `FORMAT_CHANGED` and request re-analysis/reselection. Do not silently lower quality, select a dubbed track, change containers, or start an expensive conversion.

## 5. Precise media behavior [R06 R08 R09 R10 R11]

### Compatible MP4

Treat container, video codec, audio codec, dimensions, frame rate, and processing policy separately. The default profile must produce MP4 with verified H.264, 8-bit 4:2:0 SDR video and AAC audio when the selected source has audio. Select a compatible combined stream whose audio matches the chosen track, or matching separate video/audio streams, then copy/merge without re-encoding. Unsupported or unverified HDR/color characteristics must not be silently accepted as compatible output. Merely selecting an MP4 extension, remuxing, or setting the merge container does not guarantee H.264/AAC.

Offer actual source resolutions within the configured cap, including familiar values such as 360p, 480p, 720p, and 1080p when available. Do not manufacture unavailable resolutions. Label the automatic choice “Best compatible MP4 within limit” and show the resolved dimensions before submission. Preserve portrait orientation, aspect ratio, and the selected source frame rate. Do not upscale. If the requested compatible source is unavailable, explain which choices are available.

Use display-oriented dimensions for resource caps: 1080p means a short edge at most 1080 and a long edge at most 1920; 2160p means 2160 and 3840 respectively. Apply both limits, so a 1080 by 1920 portrait source is eligible for the 1080p profile. Account for rotation metadata, preserve aspect ratio, and do not crop. A stream can be copied only if it satisfies the entire output contract; resizing, pixel-format conversion, or color conversion requires encoding even for an existing H.264 stream.

Implement optional “Convert to compatible MP4” behind `ENABLE_TRANSCODING=false`, requiring both an enabled server capability and explicit per-job consent. Use a documented, bounded H.264/AAC preset with an 8-bit 4:2:0 output. Copy already compatible streams and encode only those needing conversion. The default conversion cap is 1080p; preserve aspect ratio and never upscale. Restrict conversion to supported SDR input. If HDR/10-bit color handling cannot be verified, reject that conversion with a clear reason rather than silently producing incorrect colors. Show that conversion takes extra processing time and may lose quality. Do not promise a processing speed or output size before measurement.

### MP3

Encode the selected audio stream to MP3 at the chosen output target of 128, 192, or 320 kbps. Use a verified MP3 encoder and its bitrate mode consistently; do not confuse a VBR quality number with a bitrate. Explain once in the output details that increasing the output bitrate cannot restore detail absent from the source. Preserve the selected source language and channel layout unless an explicitly documented compatibility conversion is necessary. Do not upscale sample rate for marketing purposes. Keep metadata handling simple and safe; embedded artwork is not required.

### Original audio

Preserve the selected available audio stream without lossy re-encoding, using a compatible container and its real extension. For example, AAC may be saved as M4A and Opus retained in WebM or an appropriate Opus container. Label the actual codec/container. “Original” refers to the available platform audio stream, not the uploader's master file, lossless sound, or an MP3 file by renaming. If this operation is not available for a source, say so.

Where the source offers multiple audio tracks, show the language and original/default designation when provided. Prefer an explicitly identified original track; otherwise use a clearly labeled source default. Never infer an unknown language or silently switch to an auto-dubbed track. If selected audio is expected, a file missing that stream must fail validation rather than be presented as a successful video with sound.

Audio output may come from an audio-only rendition or the matching audio stream in a combined rendition. Do not reject audio extraction solely because no standalone audio rendition exists. Demux/copy it for Original audio, or decode/encode it for MP3, subject to the same aggregate input limits.

## 6. Durable job execution [R13 R14 R17 R18]

Persist each job before executing it and return `202 Accepted` with its identifier. Use a dedicated worker that atomically claims queued jobs in short SQLite transactions. Default media concurrency is 1. Enforce a single worker owner/lease and guard against duplicate processing. Do not use FastAPI `BackgroundTasks`, an in-memory queue, a browser connection, or one long HTTP request as the only job system.

Use these separate concepts:

- `status`: `queued | running | succeeded | failed | cancelled | interrupted`
- `phase`: `resolving | downloading | merging | transcoding | verifying`, or `null`
- `cancel_requested_at`: timestamp or `null`
- `file_state`: `none | available | expired | deleted | missing`

Record timestamps in UTC and display them in the user's locale. Store an atomic revision with each snapshot. Use an idempotency key for job creation; the same key and identical request returns the same job, while a reused key with a different request is rejected. Retrying or recreating a file creates a new job linked to the old one, with a fresh source/format check.

Use the `Idempotency-Key` header for create and retry. The retry route's path identifies the parent; reject conflicting parent information and require the fresh analysis to identify the parent's canonical source. A different source uses ordinary job creation.

Run a small engine adapter in an owned subprocess group. The adapter may embed yt-dlp and emit whitelisted NDJSON progress events; any direct FFmpeg invocation must use an argument array, `-nostdin`, bounded execution, and local input files. Do not parse human console output as the primary progress protocol. Drain stdout/stderr concurrently, bound logs, and check every return code. Do not enable “ignore errors” in a way that converts a failed postprocessor into success.

Cancellation must actually stop the entire owned process group, including FFmpeg, with a short terminate grace period followed by forced termination if necessary. A queued job cancels without launching. A running job stays running with a cancellation-requested indication until the worker has terminated its children and cleaned its own partial output. Resolve cancellation-versus-completion with an atomic terminal-state update; only one outcome wins. Do not kill a persisted PID blindly after restart.

On worker startup, preserve queued jobs and mark abandoned running jobs as interrupted only after establishing that no live owner still holds them. Reconcile partial/final files against database records, and remove only known job-owned orphans. Expose an explicit retry action. Do not promise byte-perfect resume across a crash or infer success from a leftover filename. API restarts and browser refreshes must not cancel healthy worker jobs. A worker crash, shutdown, or replacement must not leave unmanaged child processes writing indefinitely.

Use the worker container as the recovery unit. A fatal worker exit terminates the container; do not restart just Python inside a surviving container containing old media children. Replace it after its processes have been torn down. Enforce exclusive local worker ownership, such as a lifetime-held advisory lock. A stale heartbeat is diagnostic evidence, not proof that the old worker or its children have terminated. Reconcile only after exclusive ownership and prior termination are established.

## 7. Truthful progress and completion [R15 R16]

Report measured progress for the current phase. During download, use real byte counts and distinguish exact totals, estimated totals, and unknown totals. For separate audio/video transfers, avoid showing two unrelated 100% events as overall completion. Include the current stream or an honestly computed aggregate. Speed, ETA, and percent may be `null`. Use an indeterminate indicator for unknown duration or merge progress. If deriving conversion progress from FFmpeg's machine-readable output time, validate the units and duration used. Do not generate timer-based percentages or invented ETAs.

Use authenticated, same-origin SSE. Send an authoritative snapshot with a revision on connect/reconnect, then current updates. A small snapshot-based implementation is sufficient; full historical event replay is not required. If event IDs/Last-Event-ID are used, document the replay window and send a fresh snapshot when recovery is not possible. Send heartbeat comments, prevent proxy buffering, and close client streams on unmount, terminal state, or logout. Support bounded polling of `GET /jobs/{id}` as a fallback. A broken event stream changes the connection indicator, not the job outcome; do not enqueue a duplicate job to reconnect.

Revalidate session expiry and revocation server-side at every heartbeat, at most 15 seconds apart, and terminate unauthorized streams. Reject expired/revoked-session reconnections. Client-side stream cleanup is not an authentication control. Logout or session expiry must not cancel the media job.

Overall success requires all of the following: engine and postprocessors exit successfully; the final file exists and is nonempty; ffprobe confirms the expected container, stream codecs, dimensions, audio-track presence, and reasonable duration; the file is atomically published from managed staging on the same filesystem; and the database records the final artifact. A download hook reporting “finished” is not sufficient. Reconcile crashes between file publication and the database update conservatively. Unknown duration is a validation limitation, not a reason to invent a value.

## 8. Storage, file delivery, and history [R21 R22 R23 R24 R27]

Use server-controlled directories under one managed persistent data root, with separate state, temporary job, and finished-file locations. Keep staging and final media on the same filesystem for atomic publication. Use UUID-based internal paths and a sanitized human-readable download filename. Handle Korean/Unicode titles, reserved names, path separators, control characters, long names, and collisions. Never use a raw title as a path or overwrite another job's file.

The browser must not set an absolute path, an output template, or the host's Downloads directory. The operator configures an allowed root through deployment configuration. Prefer a named local volume; include an optional Windows bind-mount example for operators who want files visible in a chosen host folder. Explain Docker path mapping and permissions. Do not place SQLite WAL state on SMB/NFS or share it between hosts.

The API exposes a completed file by an opaque job/artifact ID and server-side lookup, never a user-supplied path. Enforce authentication and ownership on file reads and deletions. Verify containment and reject symlink escapes for create/read/delete operations. Do not mount output files as an unprotected static directory.

Use a streaming file response with correct MIME type, Content-Disposition, Unicode filename support, Content-Length, HEAD, and tested single-byte-range behavior. Support valid `206` and invalid `416` responses; expired/deleted files receive a clear `410`, unknown IDs a `404`. Do not build a multi-gigabyte Blob in browser memory. The browser decides where “Download to this device” saves the file; do not promise silent writes to an arbitrary client folder or use a File System Access API as a universal requirement. Separate server processing progress from the browser-managed final transfer; the website must not falsely report the latter as saved to disk.

Enforce duration, input bytes, final-file size, total job workspace, queue length, managed storage, minimum free disk space, and execution deadlines. Count separate audio/video inputs, temporary files, conversion output, and retained files. Preflight known estimates, reserve space conservatively when estimates are unknown, and monitor actual usage while jobs run. Explain that estimates and application-level sampling are not filesystem quotas. Stop cleanly on limits before deliberately exhausting storage; report a typed error and remove incomplete job-owned output.

Default finished files expire after 24 hours unless “Keep on server” was selected. Retained files still count toward the quota and are never silently removed to make space. The user may explicitly delete them. Before starting a job, expire eligible temporary results, then refuse the job if space is still insufficient. Cleanup must coordinate with active jobs and active file transfers so it does not remove an output being written or downloaded. Protect transfers with a lease or equivalent tested mechanism. A pin/expiry/delete race must have one atomic outcome. History-only removal and file deletion must be separate actions with clear consequences; retained files must remain discoverable and manageable. Keep minimal metadata or tombstones necessary to represent retained files even after ordinary history expiry.

## 9. Failure handling and service limits [R19 R20 R34]

Return a stable error envelope with `code`, localized `message`, `retryable`, optional `retry_after_seconds`, and a practical `action`. Distinguish at least:

`INVALID_URL`, `UNSUPPORTED_URL`, `SOURCE_UNAVAILABLE`, `SOURCE_AUTH_REQUIRED`, `SOURCE_FORBIDDEN`, `SOURCE_RATE_LIMITED`, `FORMAT_UNAVAILABLE`, `FORMAT_CHANGED`, `ANALYSIS_EXPIRED`, `DEPENDENCY_MISSING`, `WORKER_UNAVAILABLE`, `POSTPROCESS_FAILED`, `OUTPUT_INVALID`, `STORAGE_FULL`, `LIMIT_EXCEEDED`, `JOB_TIMEOUT`, `FILE_EXPIRED`, `FILE_MISSING`, and `ENGINE_ERROR`.

Do not infer “private video” from every 403 or translate every network failure to “invalid URL”. Preserve a bounded, redacted diagnostic for the operator and show an actionable summary to the user.

Use a shared retry budget across application, extractor, fragment downloader, and processor layers so retries do not multiply. Retry only transient failures, with jitter and an absolute deadline. On 429, respect Retry-After when provided, persist a provider cooldown, and do not retry until eligible. On 403, a single controlled refresh of expired source metadata may be attempted; if access remains blocked, stop and report it. Authentication and unsupported-content failures are not automatically retried. Distinguish an opt-in retry from a promise that an external restriction can be fixed.

One application-level controller owns each analysis/job attempt series. Two automatic retries means at most three total attempts. Disable independent nested engine/fragment retry loops where supported by the pinned version, or count them through one tested shared budget; never allocate the full budget separately to every layer. The one permitted 403 refresh consumes this budget. Provider cooldown also gates analysis, playlist inspection, worker re-resolution, and new download attempts; respond with the typed cooldown error instead of launching a new probe.

## 10. Security and privacy boundaries [R25 R26 R27 R28 R29 R32]

All browser-controlled settings must be typed and allowlisted. Never forward raw yt-dlp options, format expressions, executable hooks, postprocessor arguments, output templates, environment overrides, cookie files, proxy settings, or arbitrary paths from a request. Safe subprocess construction is necessary, and does not by itself make dangerous engine options safe. Disable implicit user configuration, unmanaged plugins, and generic extraction using the chosen engine version's documented controls.

Require one local password, established with a CLI bootstrap/reset command that reads the password without echoing it and stores only a modern password hash. No registration, multi-tenant account system, or Google account collection is needed. Fail closed before bootstrap. Password reset revokes existing sessions. Store sessions server-side and use opaque HttpOnly cookies, SameSite protection, expiry, and logout invalidation. Use Secure cookies for HTTPS. Define an explicit local-only HTTP mode for the loopback reference deployment, consistently enabled in Compose and `.env.example`, that omits only Secure while retaining HttpOnly, SameSite, session expiry, Host validation, and CSRF protection. Never embed a shared secret in the SPA, browser storage, or URL parameters.

Enforce an exact allowed Host/Origin policy and CSRF protection for state-changing requests, including deletion and cancellation. Protect login against cross-origin submission and brute-force attempts. Use a Vite development proxy and same-origin production serving; do not use wildcard CORS with credentials. Limit API bodies, analysis requests, job creation, login attempts, and simultaneous event/file streams. Health summaries may be public only when they expose no secrets or detailed paths; diagnostics, metadata, jobs, settings, and files require authentication.

Treat titles, channel names, metadata, and thumbnails as untrusted. Render plain text with normal escaping and no raw HTML. Apply appropriate security headers and a tested Content Security Policy. Serve local UI assets. For thumbnails, use a narrowly scoped server-controlled fetch with permitted hosts, validated connection destinations, bounded redirects, timeout, byte/type limits, and safe image handling; otherwise show a placeholder. Do not add a generic image proxy. Redact cookies, tokens, signed URLs, secrets, and sensitive path information from logs; keep logs bounded and remove stale data according to retention policy.

SSRF protection must cover both IPv4 and IPv6, private/loopback/link-local and metadata destinations, redirects, retries, and DNS rebinding for HTTP fetches the app controls. Validate the destination and connect to the validated address while preserving hostname/TLS verification; a separate DNS check followed by an unchecked lookup is insufficient. Reconstructing YouTube URLs and restricting extractors reduces exposure but does not prove all of yt-dlp's internal media/CDN requests are constrained.

Document the actual network boundary. The required baseline is an authenticated loopback-only personal deployment. Do not claim public-hosting or complete SSRF protection from an input allowlist alone. Any separately supplied remote-access profile must enforce and test outbound destination controls across the engine and media requests, disable cloud metadata access, and use private access or an authenticated HTTPS reverse proxy. A VPN solves access to the UI, not unrestricted outbound requests. If these controls cannot be implemented and verified, explicitly leave that deployment profile unsupported and continue delivering the local reference application.

## 11. Deployment and operator defaults [R22 R30 R31 R32]

Provide a multi-stage Dockerfile and `docker-compose.yml` for `app` and `worker`, with a shared application image and named local data volume. Publish only `127.0.0.1:8000:8000` by default; the worker has no published port. Use a non-root runtime, explicit writable mounts, dropped capabilities, no-new-privileges, an init/reaping strategy, stop grace periods, health checks, bounded logs, and CPU/memory limits appropriate to one worker. Do not mount the Docker socket, the host filesystem, browser profiles, or secrets unrelated to this app. Set volume ownership during a documented initialization step, not by running the whole application permanently as root.

Use one consistent set of defaults in code, API diagnostics, `.env.example`, UI help, README, and tests. These are proposed product defaults, not claims about YouTube or library limits:

| Setting | Default |
| --- | --- |
| Media concurrency | 1 |
| Analysis concurrency | 1, globally bounded |
| Maximum waiting jobs | 20 |
| Analysis TTL and deadline | 10 minutes and 60 seconds |
| Maximum source duration | 4 hours |
| Native MP4 resolution cap | 2160p; default selection up to 1080p |
| Explicit conversion cap | 1080p SDR |
| MP3 default | 192 kbps |
| Aggregate input and final-file limits | 5 GiB each |
| Per-job workspace limit | 12 GiB including inputs and output |
| Total managed media storage | 50 GiB |
| Minimum free space | 2 GiB |
| Active-job deadline | 2 hours, excluding queue waiting |
| Unretained finished-file TTL | 24 hours |
| Ordinary history retention | 90 days; retained-file records remain |
| Automatic transient retries | At most 2 within the shared retry budget |
| Playlist inspection | Disabled; first 20 entries when enabled |
| Video conversion | Disabled until operator enables it |

Do not claim these defaults fit every machine. Document the required disk headroom and how to tune limits before large jobs. Keep high-risk controls and server paths in operator configuration; expose only safe personal preferences in the settings page. Check startup for inconsistent limits and unsupported configuration.

The source-duration and active-job limits are independent. Source eligibility does not guarantee completion before the processing deadline. Active time includes resolving, retries, transfer, postprocessing, and verification, but excludes queue waiting. Show this policy before an explicitly requested conversion.

Write tested Linux/macOS shell and Windows PowerShell setup instructions: prerequisites, build, initialization, password setup, startup, open URL, storage mapping, diagnostics, stop/restart, backup, restore, upgrade, and rollback. Keep persistent data across a normal restart/update. Explain that volume deletion is destructive; it must not be part of normal update instructions. For a consistent SQLite backup, use the backup API or a documented quiesced procedure rather than copying only a live database file while ignoring its WAL.

## 12. API and code organization [R34]

Use a versioned API prefix and schemas generated/documented through FastAPI/OpenAPI. Keep frontend types aligned with the backend. Reject extra or unsupported request fields. Implement at least the following routes, with consistent authentication and CSRF rules:

| Method and route | Contract |
| --- | --- |
| `POST /api/v1/auth/login` | Establish the local session; no credential logging |
| `POST /api/v1/auth/logout` | Invalidate the current session |
| `GET /api/v1/auth/session` | Authenticated state and CSRF material as appropriate |
| `POST /api/v1/analyses` | Bounded single-video analysis; opaque choices |
| `POST /api/v1/playlists/analyze` | Optional bounded selection metadata; rejects when disabled |
| `POST /api/v1/jobs` | Validated output choice and idempotency key; 202 |
| `GET /api/v1/jobs` | Paginated/filterable history and current jobs |
| `GET /api/v1/jobs/{id}` | Current authoritative snapshot |
| `GET /api/v1/jobs/{id}/events` | Authenticated SSE snapshots/updates |
| `POST /api/v1/jobs/{id}/cancel` | Idempotent cancellation request |
| `POST /api/v1/jobs/{id}/retry` | New job using a freshly validated choice; no stale fallback |
| `GET, HEAD /api/v1/jobs/{id}/file` | Authenticated verified file and byte ranges |
| `PATCH /api/v1/jobs/{id}/retention` | Keep or expire a finished file, subject to policy |
| `DELETE /api/v1/jobs/{id}/file` | Explicit file deletion with transfer/race protection |
| `DELETE /api/v1/jobs/{id}` | Remove ordinary history only when it will not orphan a file |
| `GET, PATCH /api/v1/settings` | Safe, typed user preferences |
| `GET /healthz` | Minimal process liveness |
| `GET /api/v1/diagnostics` | Protected capability, worker, storage, and version status |

Keep the job and output-choice schemas concrete. A create request contains an `analysis_id`, an opaque `choice_id`, a `keep_on_server` boolean, and any allowed conversion consent. A retry request uses a new valid analysis/choice; the route path supplies the parent job ID. The idempotency key is a header. Requests never carry raw engine flags or direct media URLs. Use a consistent error object, for example:

```json
{
  "error": {
    "code": "FORMAT_CHANGED",
    "message": "The selected compatible format is no longer available.",
    "retryable": false,
    "action": "Analyze the URL again and choose an available output."
  }
}
```

Organize code by responsibility, with real implementations for configuration, database/migrations, schemas, authentication, URL policy, analysis, output planning, job repository, worker supervision, engine adapter, media validation, storage/cleanup, diagnostics, and routes. Example locations are `backend/app/services/format_planner.py`, `backend/app/worker.py`, `backend/app/engine_runner.py`, and `frontend/src/features/downloads/`. An equivalent clear structure is acceptable. Put required behavior in working modules, not TODO comments.

## 13. Coding sequence and completion gates [R35 R36]

Execute these phases in order, keeping a concise implementation checklist in the repository. Complete each phase's working path before adding optional features. Do not ask repeated questions about defaults already specified here.

1. **Environment and foundation:** inspect capabilities; establish the fixed stack, dependency lockfiles, Compose services, volume initialization, database migrations, bootstrap authentication, and diagnostics. Gate: a fresh local start serves the real UI/API and reports worker/storage/tool readiness accurately.
2. **Single-source engine:** implement URL normalization, bounded analysis, sanitized metadata, track-aware format planning, compatible MP4, MP3, original audio, and ffprobe validation. Gate: generated local media fixtures demonstrate real output files with correct codecs and no mislabeled formats.
3. **Durable jobs:** implement atomic queue claims, idempotency, subprocess supervision, real progress, snapshots/SSE, cancellation, and restart reconciliation. Gate: browser/API restarts do not duplicate jobs, and cancellation/worker restart cannot produce false success.
4. **Files and complete UI:** connect the real workflow, authenticated range streaming, retention/history, quota management, accessible Korean/English UI, and light/dark layouts. Gate: one end-to-end local fixture job produces a valid file, survives refresh, can be saved again, and expires/deletes accurately.
5. **Bounded optional features and hardening:** implement the specified feature-flagged SDR conversion and limited playlist selection; verify disabled behavior and allowed behavior. Test request validation, path confinement, local authentication, CSRF/Origin, metadata handling, limits, cleanup races, and dependency failures. Keep other-platform/remote-public profiles out of scope unless separately implemented and verified.
6. **Delivery verification:** build from a clean setup, run meaningful automated checks and an opt-in live smoke test when an authorized URL and environment are available. Fix failures, then report precise results, remaining external dependencies, and operator commands. Never describe a skipped check as passed.

## 14. Required tests and evidence [R35]

Use focused tests for meaningful behavior. Default CI must be reproducible without reaching YouTube. Generate short synthetic audio/video fixtures with FFmpeg and use a deterministic source adapter for queue/API tests. Keep test adapters out of production configuration and label any preview fixtures clearly. Test both the output planner and real FFmpeg output; a mock of the media engine alone is insufficient.

| Test | Required evidence |
| --- | --- |
| T01 URL and scope | Valid link variants normalize correctly; lookalikes, credentials, internal IPs, bad schemes, pure channels/playlists in single mode, and live/upcoming sources are rejected |
| T02 MP4 contract | Compatible separate and combined sources produce actual H.264/AAC, 8-bit 4:2:0 SDR MP4; landscape/portrait dimensions satisfy both edge caps; VP9/AV1 is not silently labeled H.264 |
| T03 Conversion policy | Disabled/missing-consent conversions are rejected; enabled SDR conversion works; unsupported HDR handling fails clearly |
| T04 Audio contract | Audio-only and combined inputs work; 128/192/320 MP3 targets and real output codec are verified with sensible bitrate tolerance; original audio preserves codec and valid container; selected language is retained |
| T05 Stale analysis | TTL is checked on acceptance; an accepted queued job remains valid after analysis expiry; changed formats/tracks return correct errors with no silent downgrade |
| T06 Job durability | Idempotent create/retry and competing claims do not duplicate work; conflicting requests are rejected; API/browser restart preserves jobs; worker recovery waits for prior process teardown and exclusive ownership, then marks abandoned work interrupted |
| T07 Cancellation | Cancel during download and processing kills the owned process group, cleans partial files, and has a deterministic race outcome against success |
| T08 Completion honesty | Postprocessor/ffprobe failure or a missing/empty/wrong-codec file never produces success or an enabled file link |
| T09 Progress connection | Unknown totals remain unknown; reconnect/polling restores state without creating jobs; the server enforces session expiry/revocation within 15 seconds and rejects reconnects without cancelling the media job |
| T10 File delivery | Authenticated GET/HEAD, bytes and MIME/filename, valid 206, invalid 416, missing/expired 404/410 behavior, and large-file streaming avoid whole-file buffering |
| T11 Storage lifecycle | Aggregate inputs/temp/output/retained files count toward limits; unknown-size growth stops; active writes/transfers are protected from cleanup; expired and pinned files behave correctly |
| T12 Request and file security | Arbitrary flags/paths are rejected; shell-shaped strings are inert; traversal/symlink escapes, unauthenticated files, CSRF, wrong Host/Origin, and XSS metadata fail safely |
| T13 External failures | Fixture 403/429/auth/removed-source/timeout/dependency errors map correctly; the controller permits at most three total attempts, including the one allowed 403 refresh; a persisted 429 cooldown gates all provider probes and downloads |
| T14 Optional playlist | Disabled endpoint rejects; enabled inspection is capped before fetching the whole list; each selected eligible item receives its own analyzed choice/job |
| T15 Packaging and UI | Clean build/start, migration/bootstrap, volume persistence, responsive light/dark screens, keyboard actions, Korean/English strings, and capability states work |
| T16 Live source smoke test | Separate opt-in test with `LIVE_TEST_URL` provided by the operator and confirmed permitted for download; record date, environment, dependency versions, actual output/ffprobe result, and pass/fail/skip reason |

Do not use a public live video as a mandatory CI dependency. If live extraction is unavailable or access is blocked, report that limitation while still delivering and testing the complete local application. A locally verified media pipeline does not establish present YouTube availability. Do not label the application universally “production-ready”; describe the exact deployment and checks that passed.

## 15. Required deliverables

Deliver the complete repository or downloadable project archive, including:

- Working frontend, backend, worker, engine adapter, migrations, and tests.
- Multi-stage Dockerfile, `docker-compose.yml`, `.dockerignore`, `.gitignore`, and safe `.env.example`.
- Resolved dependency lockfiles and a tested version/capability record.
- A README with setup and use instructions, the real architecture, defaults, file locations, password setup/reset, failure diagnosis, source availability limits, upgrade/rollback, backup/restore, and third-party notices.
- An API contract and a concise architecture/decision note explaining the worker, format policy, privacy, and local deployment boundary.
- A verification report listing commands actually run, outcomes, any blocked checks, optional features' status, and a requirement-to-code/test mapping for R01–R36 and T01–T16.

Finish with the exact startup commands, the local URL, the main files created, and the most material remaining limitations. Never include live credentials, cookies, private logs, temporary media URLs, invented benchmark claims, or placeholders in required implementation paths.

## 16. Official reference starting points

Recheck mutable technical requirements when implementing. These links provide context; this document's product defaults and coding plan are design decisions, not upstream guarantees.

- yt-dlp: https://github.com/yt-dlp/yt-dlp
- EJS setup: https://github.com/yt-dlp/yt-dlp/wiki/EJS
- yt-dlp FAQ: https://github.com/yt-dlp/yt-dlp/wiki/FAQ
- FFmpeg: https://ffmpeg.org/ffmpeg.html
- ffprobe: https://ffmpeg.org/ffprobe.html
- FastAPI background work: https://fastapi.tiangolo.com/tutorial/background-tasks/
- SQLite WAL: https://sqlite.org/wal.html
- Starlette file responses: https://starlette.dev/responses/
- SSE: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- SSRF controls: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- Docker port publishing: https://docs.docker.com/engine/network/port-publishing/
- Cobalt API and instance distinction: https://github.com/imputnet/cobalt/blob/main/api/README.md
- MeTube: https://github.com/alexta69/metube
- YouTube terms: https://www.youtube.com/static?template=terms
- Own-upload downloads: https://support.google.com/youtube/answer/56100?hl=en

