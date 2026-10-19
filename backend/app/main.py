"""FastAPI application: local session, analysis, jobs, and file delivery."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from app.config import Settings, load_settings, validate_limits
from app.db import connect, init_db, utc_iso, utc_now
from app.diagnostics import diagnostics
from app.errors import AppError, envelope, localize
from app.request_limits import RequestBodyLimit
from app.public_models import PublicAnalysis, PublicJob, PublicJobPage, PublicSession, PublicReadiness, PublicSettings, PublicPlaylist
from app.schemas import JobCreateBody, PasswordBody, RetentionBody, SettingsPatch, UrlBody
from app.security import (
    cookie_kwargs,
    create_session,
    host_allowed,
    login_throttled,
    operator_exists,
    origin_allowed,
    record_login,
    revoke_session,
    session_from_token,
    set_password,
    touch_session,
    verify_password,
)
from app.services.analysis import analyze_playlist, analyze_video, load_analysis
from app.services.jobs import create_job, delete_file, delete_history, list_jobs, request_cancel, set_retention, snapshot
from app.services.safe_http import fetch_thumbnail
from app.services.storage import ensure_dirs

CSP = (
    "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; "
    "script-src 'self' https://grok.com; font-src 'self'; connect-src 'self'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'self'; object-src 'none'"
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    validate_limits(settings)
    ensure_dirs(settings)
    init_db(settings).close()
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            from app.engine_runner import stop_owned_engines
            stop_owned_engines()

    app = FastAPI(title="Seorap", version="1.0.0", openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.url.path in {'/', '/index.html'}:
            request.state.style_nonce = secrets.token_urlsafe(18)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path in {"/", "/index.html"}:
            response.headers["Content-Security-Policy"] = CSP.replace("style-src 'self'", f"style-src 'self' 'nonce-{request.state.style_nonce}'")
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        response = JSONResponse(status_code=exc.status, content=envelope(exc, _locale(request, settings)))
        if exc.retry_after is not None:
            response.headers["Retry-After"] = str(exc.retry_after)
        return response

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content=envelope(AppError("BAD_REQUEST", 400), _locale(request, settings)))

    def db():
        conn = connect(settings)
        try:
            yield conn
        finally:
            conn.close()

    def locale_of(request: Request, conn=None) -> str:
        header = request.headers.get("x-locale", "")
        if header in {"ko", "en"}:
            return header
        if conn is not None:
            row = conn.execute("SELECT language FROM preferences WHERE id = 1").fetchone()
            if row and row["language"] in {"ko", "en"}:
                return row["language"]
        return "ko"

    def require_session(request: Request, conn=Depends(db)):
        if not host_allowed(settings, request.headers.get("host")):
            raise AppError("CSRF_FAILED", 403)
        row = session_from_token(conn, request.cookies.get(settings.cookie_name))
        if row is None:
            raise AppError("UNAUTHORIZED", 401)
        touch_session(conn, row["id"])
        request.state.session = row
        request.state.locale = locale_of(request, conn)
        return row

    def require_csrf(request: Request, session=Depends(require_session)):
        if request.headers.get("x-requested-with") != "seorap":
            raise AppError("CSRF_FAILED", 403)
        if not origin_allowed(settings, request.headers.get("origin"), request.headers.get("host")):
            raise AppError("CSRF_FAILED", 403)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf_secret"]):
            raise AppError("CSRF_FAILED", 403)
        return session

    def ensure_preferences(conn) -> None:
        if conn.execute("SELECT id FROM preferences WHERE id = 1").fetchone() is None:
            conn.execute(
                "INSERT INTO preferences (id, language, theme, mp3_bitrate, updated_at) VALUES (1, 'ko', 'system', ?, ?)",
                (settings.mp3_default_kbps, utc_iso()),
            )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/api/v1/auth/bootstrap")
    def bootstrap(body: PasswordBody, request: Request, conn=Depends(db)):
        _guard_entry(request, settings)
        if not settings.allow_http_bootstrap:
            raise AppError("NOT_BOOTSTRAPPED", 403)
        peer = request.client.host if request.client else ""
        if peer not in {"127.0.0.1", "::1", "testclient"}:
            raise AppError("CSRF_FAILED", 403)
        if operator_exists(conn):
            raise AppError("ALREADY_BOOTSTRAPPED", 409)
        set_password(conn, body.password, initial_only=True)
        ensure_preferences(conn)
        return {"bootstrapped": True}

    @app.post("/api/v1/auth/login", response_model=PublicSession)
    def login(body: PasswordBody, request: Request, conn=Depends(db)):
        _guard_entry(request, settings)
        if not operator_exists(conn):
            raise AppError("NOT_BOOTSTRAPPED", 503)
        ip = request.client.host if request.client else "local"
        wait = login_throttled(conn, ip)
        if wait:
            raise AppError("LOGIN_THROTTLED", 429, retryable=True, retry_after=wait)
        row = conn.execute("SELECT password_hash FROM operator WHERE id = 1").fetchone()
        if not row or not verify_password(body.password, row["password_hash"]):
            record_login(conn, ip, False)
            raise AppError("BAD_PASSWORD", 401)
        record_login(conn, ip, True)
        ensure_preferences(conn)
        _sid, token, _csrf = create_session(conn, settings)
        response = JSONResponse(session_payload(conn, settings, token))
        response.set_cookie(settings.cookie_name, token, **cookie_kwargs(settings))
        return response

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, session=Depends(require_csrf), conn=Depends(db)):
        revoke_session(conn, session["id"])
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(settings.cookie_name, path="/")
        return response

    @app.get("/api/v1/auth/session", response_model=PublicSession)
    def session_route(request: Request, conn=Depends(db)):
        if not host_allowed(settings, request.headers.get("host")):
            raise AppError("CSRF_FAILED", 403)
        token = request.cookies.get(settings.cookie_name)
        row = session_from_token(conn, token)
        if row is None and not settings.require_password:
            ensure_preferences(conn)
            _sid, token, _csrf = create_session(conn, settings)
            response = JSONResponse(session_payload(conn, settings, token))
            response.set_cookie(settings.cookie_name, token, **cookie_kwargs(settings))
            return response
        if row is None:
            return {
                "authenticated": False, "bootstrapped": operator_exists(conn), "password_required": True,
                "bootstrap_allowed": settings.allow_http_bootstrap and (request.client.host if request.client else '') in {'127.0.0.1', '::1', 'testclient'},
                "bootstrap_method": 'browser' if settings.allow_http_bootstrap else 'cli',
            }
        touch_session(conn, row["id"])
        return session_payload(conn, settings, token)

    @app.post("/api/v1/analyses", response_model=PublicAnalysis)
    def analyses(body: UrlBody, session=Depends(require_csrf)):
        return analyze_video(settings, body.url)

    @app.get("/api/v1/analyses/{analysis_id}/thumbnail")
    def thumbnail(analysis_id: str, session=Depends(require_session), conn=Depends(db)):
        try:
            record = load_analysis(conn, analysis_id, require_fresh=False)
        except AppError as exc:
            if exc.code == "NOT_FOUND":
                raise
            raise
        url = (record["metadata"] or {}).get("thumbnail")
        if not url:
            raise AppError("NOT_FOUND", 404)
        data, ctype = fetch_thumbnail(url)
        return Response(content=data, media_type=ctype)

    @app.post("/api/v1/playlists/analyze", response_model=PublicPlaylist)
    def playlists(body: UrlBody, session=Depends(require_csrf)):
        return analyze_playlist(settings, body.url)

    @app.post("/api/v1/jobs", status_code=202, response_model=PublicJob)
    def jobs_create(
        body: JobCreateBody,
        request: Request,
        session=Depends(require_csrf),
        conn=Depends(db),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        key = _idempotency(idempotency_key)
        digest = _hash_body(body, None)
        snap = create_job(
            conn,
            settings,
            analysis_id=body.analysis_id,
            choice_id=body.choice_id,
            keep_on_server=body.keep_on_server,
            conversion_consent=body.conversion_consent,
            idempotency_key=key,
            request_hash=digest,
        )
        return present_job(snap, _locale(request, settings, conn))

    @app.get("/api/v1/jobs", response_model=PublicJobPage)
    def jobs_list(
        request: Request,
        status: str | None = None,
        search: str | None = None,
        format: str | None = None,
        active: bool | None = None,
        file_state: str | None = None,
        limit: int = 20,
        offset: int = 0,
        session=Depends(require_session),
        conn=Depends(db),
    ):
        if status and status not in {"queued", "running", "succeeded", "failed", "cancelled", "interrupted"}:
            raise AppError("BAD_REQUEST", 400)
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        if format and format not in {'mp4', 'mp3', 'original_audio'}:
            raise AppError('BAD_REQUEST', 400)
        if file_state and file_state not in {'none', 'available', 'expired', 'deleted', 'missing'}:
            raise AppError('BAD_REQUEST', 400)
        payload = list_jobs(conn, status=status, limit=limit, offset=offset, search=search, format=format, active=active, file_state=file_state)
        locale = _locale(request, settings, conn)
        payload["jobs"] = [present_job(job, locale) for job in payload["jobs"]]
        return payload

    @app.get("/api/v1/jobs/{job_id}", response_model=PublicJob)
    def jobs_get(job_id: str, request: Request, session=Depends(require_session), conn=Depends(db)):
        return present_job(snapshot(conn, job_id), _locale(request, settings, conn))

    @app.get("/api/v1/jobs/{job_id}/events")
    def jobs_events(job_id: str, request: Request, session=Depends(require_session)):
        import asyncio

        locale = request.state.locale

        async def gen():
            last = -1
            elapsed = 0.0
            while True:
                conn = connect(settings)
                try:
                    current = session_from_token(conn, request.cookies.get(settings.cookie_name))
                    if current is None or current["revoked_at"] or current["expires_at"] <= utc_iso():
                        yield "event: bye\ndata: {\"authenticated\": false}\n\n"
                        return
                    try:
                        snap = present_job(snapshot(conn, job_id), locale)
                    except AppError:
                        yield "event: bye\ndata: {\"error\": \"not-found\"}\n\n"
                        return
                finally:
                    conn.close()
                if snap["revision"] != last:
                    last = snap["revision"]
                    yield f"event: snapshot\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n"
                else:
                    yield ": heartbeat\n\n"
                if snap["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                    return
                await asyncio.sleep(settings.sse_heartbeat_seconds)
                elapsed += settings.sse_heartbeat_seconds

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=PublicJob)
    def jobs_cancel(job_id: str, request: Request, session=Depends(require_csrf), conn=Depends(db)):
        return present_job(request_cancel(conn, job_id), _locale(request, settings, conn))

    @app.post("/api/v1/jobs/{job_id}/retry", status_code=202, response_model=PublicJob)
    def jobs_retry(
        job_id: str,
        body: JobCreateBody,
        request: Request,
        session=Depends(require_csrf),
        conn=Depends(db),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        key = _idempotency(idempotency_key)
        digest = _hash_body(body, job_id)
        snap = create_job(
            conn,
            settings,
            analysis_id=body.analysis_id,
            choice_id=body.choice_id,
            keep_on_server=body.keep_on_server,
            conversion_consent=body.conversion_consent,
            idempotency_key=key,
            request_hash=digest,
            parent_job_id=job_id,
        )
        return present_job(snap, _locale(request, settings, conn))

    @app.api_route("/api/v1/jobs/{job_id}/file", methods=["GET", "HEAD"])
    def jobs_file(job_id: str, request: Request, session=Depends(require_session), conn=Depends(db)):
        return file_response(settings, conn, job_id, request)

    @app.patch("/api/v1/jobs/{job_id}/retention", response_model=PublicJob)
    def jobs_retention(job_id: str, body: RetentionBody, request: Request, session=Depends(require_csrf), conn=Depends(db)):
        return present_job(set_retention(conn, settings, job_id, body.keep_on_server), _locale(request, settings, conn))

    @app.delete("/api/v1/jobs/{job_id}/file", response_model=PublicJob)
    def jobs_delete_file(job_id: str, request: Request, session=Depends(require_csrf), conn=Depends(db)):
        return present_job(delete_file(conn, settings, job_id), _locale(request, settings, conn))

    @app.delete("/api/v1/jobs/{job_id}")
    def jobs_delete(job_id: str, session=Depends(require_csrf), conn=Depends(db)):
        delete_history(conn, job_id)
        return Response(status_code=204)

    @app.get("/api/v1/settings", response_model=PublicSettings)
    def settings_get(session=Depends(require_session), conn=Depends(db)):
        ensure_preferences(conn)
        row = conn.execute("SELECT language, theme, mp3_bitrate FROM preferences WHERE id = 1").fetchone()
        from app.services.storage import managed_bytes

        return {
            "language": row["language"],
            "theme": row["theme"],
            "mp3_bitrate": row["mp3_bitrate"],
            "capabilities": {
                "playlists_enabled": settings.enable_playlists,
                "transcoding_enabled": settings.enable_transcoding,
                "demo_data": settings.demo_data,
                "max_source_duration_seconds": settings.max_source_duration_seconds,
                "file_ttl_seconds": settings.file_ttl_seconds,
                "storage_limit_bytes": settings.max_storage_bytes,
                "storage_used_bytes": managed_bytes(settings),
                "native_cap": settings.native_mp4_cap,
                "default_cap": settings.default_mp4_cap,
                "mp3_rates": [128, 192, 320],
            },
        }

    @app.patch("/api/v1/settings", response_model=PublicSettings)
    def settings_patch(body: SettingsPatch, session=Depends(require_csrf), conn=Depends(db)):
        ensure_preferences(conn)
        current = conn.execute("SELECT language, theme, mp3_bitrate FROM preferences WHERE id = 1").fetchone()
        language = body.language or current["language"]
        theme = body.theme or current["theme"]
        bitrate = body.mp3_bitrate or current["mp3_bitrate"]
        conn.execute(
            "UPDATE preferences SET language = ?, theme = ?, mp3_bitrate = ?, updated_at = ? WHERE id = 1",
            (language, theme, bitrate, utc_iso()),
        )
        return settings_get(session=session, conn=conn)

    @app.get("/api/v1/diagnostics")
    def diagnostics_route(session=Depends(require_session), conn=Depends(db)):
        return diagnostics(settings, conn)

    @app.get('/api/v1/readiness', response_model=PublicReadiness)
    def processing_readiness(session=Depends(require_session), conn=Depends(db)):
        info = diagnostics(settings, conn)
        worker_ready = bool(info.get('worker') and not info['worker']['stale'])
        dependencies_ready = bool(info.get('dependencies_ready'))
        reasons = []
        if not worker_ready:
            reasons.append('WORKER_UNAVAILABLE')
        if not dependencies_ready:
            reasons.append('DEPENDENCY_MISSING')
        if info['free_bytes'] < settings.min_free_bytes:
            reasons.append('STORAGE_FULL')
        return {'processing_ready': bool(info['ready']), 'worker_ready': worker_ready, 'dependencies_ready': bool(dependencies_ready), 'reasons': reasons}

    static_dir = Path(__file__).resolve().parent / "static"
    index = static_dir / "index.html"
    if index.exists():
        @app.get('/', include_in_schema=False)
        @app.get('/index.html', include_in_schema=False)
        def spa_index(request: Request):
            return HTMLResponse(render_spa_index(index.read_text(encoding='utf-8'), request.state.style_nonce), headers={'Cache-Control': 'no-store'})

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    app.add_middleware(RequestBodyLimit)
    return app


def render_spa_index(document: str, nonce: str) -> str:
    # Trusted code reads this nonce before Radix inserts its scroll-lock styles.
    return document.replace('<head>', f'<head><meta name="csp-style-nonce" content="{nonce}">', 1)


def _locale(request: Request, settings: Settings | None = None, conn=None) -> str:
    if request is None:
        return "ko"
    header = (request.headers.get("x-locale") or "").lower()
    if header in {"ko", "en"}:
        return header
    if hasattr(request.state, "locale"):
        return request.state.locale
    return "ko"


def _guard_entry(request: Request, settings: Settings) -> None:
    if not host_allowed(settings, request.headers.get("host")):
        raise AppError("CSRF_FAILED", 403)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise AppError("BAD_REQUEST", 415)
    if request.headers.get("x-requested-with") != "seorap":
        raise AppError("CSRF_FAILED", 403)
    if not origin_allowed(settings, request.headers.get("origin"), request.headers.get("host")):
        raise AppError("CSRF_FAILED", 403)


def _idempotency(value: str | None) -> str:
    if not value or len(value) < 8 or len(value) > 200:
        raise AppError("IDEMPOTENCY_REQUIRED", 400)
    return value


def _hash_body(body: JobCreateBody, parent: str | None) -> str:
    payload = body.model_dump()
    payload["parent_job_id"] = parent
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def session_payload(conn, settings: Settings, token: str | None) -> dict[str, Any]:
    row = session_from_token(conn, token)
    if row is None:
        return {"authenticated": False, "bootstrapped": operator_exists(conn), "bootstrap_allowed": settings.allow_http_bootstrap, "bootstrap_method": 'browser' if settings.allow_http_bootstrap else 'cli'}
    prefs = conn.execute("SELECT language, theme FROM preferences WHERE id = 1").fetchone()
    return {
        "authenticated": True,
        "bootstrapped": True,
        "csrf_token": row["csrf_secret"],
        "expires_at": row["expires_at"],
        "language": prefs["language"] if prefs else "ko",
        "theme": prefs["theme"] if prefs else "system",
        "password_required": settings.require_password,
        "bootstrap_allowed": False,
        "bootstrap_method": None,
    }


def present_job(snap: dict[str, Any], locale: str) -> dict[str, Any]:
    error = snap.get("error")
    if not error:
        return snap
    code = error.get("code") or "ENGINE_ERROR"
    message, action = localize(code, locale)
    body = {"code": code, "message": message, "retryable": bool(error.get("retryable")), "action": action}
    if error.get("retry_after_seconds") is not None:
        body["retry_after_seconds"] = error["retry_after_seconds"]
    return {**snap, "error": body}


def file_response(settings: Settings, conn, job_id: str, request: Request) -> Response:
    from app.services.storage import open_artifact, release_lease, renew_lease
    opened = open_artifact(conn, settings, job_id)
    artifact, size = opened.artifact, opened.size
    filename = artifact.get("filename") or "download"
    mime = artifact.get("mime") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = f"attachment; filename=\"download{Path(filename).suffix}\"; filename*=UTF-8''{quote(filename, safe='')}"
    headers = {"Accept-Ranges": "bytes", "Content-Disposition": disposition,
               "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    closed = False

    def cleanup():
        nonlocal closed
        if closed:
            return
        closed = True
        opened.handle.close()
        closer = connect(settings)
        try:
            release_lease(closer, opened.lease_id)
        finally:
            closer.close()

    try:
        byte_range = _parse_range(request.headers.get("range"), size)
    except AppError:
        cleanup()
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}, media_type=mime)
    start, end = (0, size - 1) if byte_range is None else byte_range
    length = end - start + 1
    status = 200 if byte_range is None else 206
    headers["Content-Length"] = str(length)
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if request.method == "HEAD":
        cleanup()
        return Response(status_code=status, headers=headers, media_type=mime)

    async def chunks():
        import asyncio
        import contextlib

        async def renew():
            while True:
                await asyncio.sleep(30)
                renewal = connect(settings)
                try:
                    if not renew_lease(renewal, opened.lease_id):
                        raise OSError('Transfer lease lost')
                finally:
                    renewal.close()

        renewal_task = asyncio.create_task(renew())
        try:
            opened.handle.seek(start)
            remaining = length
            while remaining > 0:
                # A fixed chunk keeps memory bounded, even for multi-GiB media.
                piece = await asyncio.to_thread(opened.handle.read, min(64 * 1024, remaining))
                if not piece:
                    raise OSError('Artifact changed during transfer')
                if renewal_task.done():
                    renewal_task.result()
                remaining -= len(piece)
                yield piece
        finally:
            renewal_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError):
                await renewal_task
            cleanup()

    return StreamingResponse(chunks(), status_code=status, media_type=mime, headers=headers, background=BackgroundTask(cleanup))


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    if not header.startswith("bytes=") or "," in header:
        raise AppError("BAD_REQUEST", 416, extra={"message": "Only a single byte range is supported.", "action": "Request one range, or download the whole file."})
    spec = header[6:]
    try:
        if spec.startswith("-"):
            count = int(spec[1:])
            if count <= 0:
                raise ValueError
            start = max(0, size - count)
            end = size - 1
        else:
            start_text, end_text = spec.split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError as exc:
        raise AppError("BAD_REQUEST", 416) from exc
    if start < 0 or start >= size or end < start:
        raise AppError("BAD_REQUEST", 416)
    return start, min(end, size - 1)


app = create_app()
