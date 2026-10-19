"""Exclusive single-task worker with an independent control/housekeeping loop."""

from __future__ import annotations

import fcntl
import json
import math
import os
import random
import signal
import socket
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from app.config import Settings, load_settings, validate_limits
from app.db import connect, init_db, transaction, utc_iso, utc_now
from app.engine_runner import cleanup_stale_engines, execute, stop_owned_engines
from app.errors import AppError
from app.services.analysis import _cooldown_seconds, set_cooldown
from app.services.storage import (
    ensure_dirs, expire_finished_files, free_bytes, job_final_dir, job_workspace,
    directory_size, prune_old_history, publish_file, reconcile_reservations,
    recheck_reservation, release_reservation, remove_tree, safe_download_name,
)

NON_RETRYABLE = {
    "SOURCE_AUTH_REQUIRED", "SOURCE_FORBIDDEN", "SOURCE_UNAVAILABLE", "FORMAT_CHANGED",
    "FORMAT_UNAVAILABLE", "OUTPUT_INVALID", "POSTPROCESS_FAILED", "DEPENDENCY_MISSING",
    "STORAGE_FULL", "LIMIT_EXCEEDED", "CONSENT_REQUIRED", "TRANSCODING_DISABLED",
}
CONTROL_INTERVAL_SECONDS = 0.2
HEARTBEAT_INTERVAL_SECONDS = 1.0
HOUSEKEEPING_INTERVAL_SECONDS = 5.0


def _worker_id(settings: Settings) -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire_worker_lock(settings: Settings):
    ensure_dirs(settings)
    handle = open(settings.data_dir / "worker.lock", "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit("Another worker already holds the local lock.")
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def reconcile_abandoned(settings: Settings) -> int:
    """Only after the exclusive lock: stop old writers before cleaning their files."""
    cleanup_stale_engines(settings)
    conn = connect(settings)
    now = utc_iso()
    try:
        with transaction(conn):
            rows = conn.execute("SELECT id, file_state FROM jobs WHERE status = 'running'").fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE jobs SET status = 'interrupted', phase = NULL, finished_at = ?, updated_at = ?,
                       revision = revision + 1, progress_json = NULL, error_json = ?
                       WHERE id = ? AND status = 'running'""",
                    (now, now, json.dumps({"code": "INTERRUPTED", "retryable": True}), row["id"]),
                )
                release_reservation(conn, row["id"])
            reconcile_reservations(conn, settings)
    finally:
        conn.close()
    for row in rows:
        remove_tree(job_workspace(settings, row["id"]))
        if row["file_state"] != "available":
            remove_tree(job_final_dir(settings, row["id"]))
    return len(rows)


def beat(settings: Settings, worker_id: str) -> None:
    conn = connect(settings)
    try:
        conn.execute(
            """INSERT INTO worker_heartbeat (id, worker_id, beat_at, pid) VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET worker_id = excluded.worker_id,
               beat_at = excluded.beat_at, pid = excluded.pid""",
            (worker_id, utc_iso(), os.getpid()),
        )
    finally:
        conn.close()


def claim_next(settings: Settings, worker_id: str) -> str | None:
    conn = connect(settings)
    failed: str | None = None
    try:
        with transaction(conn):
            if _cooldown_seconds(conn):
                return None
            if conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE status = 'running'").fetchone()["c"]:
                return None
            now = utc_now()
            row = conn.execute(
                """SELECT id, next_attempt_at, active_deadline_at FROM jobs WHERE status = 'queued' AND cancel_requested_at IS NULL
                   AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   ORDER BY created_at, id LIMIT 1""", (utc_iso(now),),
            ).fetchone()
            if row is None:
                return None
            try:
                recheck_reservation(conn, settings, row["id"])
            except AppError as exc:
                conn.execute(
                    """UPDATE jobs SET status = 'failed', phase = NULL, finished_at = ?, updated_at = ?,
                       revision = revision + 1, error_json = ? WHERE id = ? AND status = 'queued'""",
                    (utc_iso(now), utc_iso(now), json.dumps({"code": exc.code, "retryable": False}), row["id"]),
                )
                release_reservation(conn, row["id"])
                failed = row["id"]
            if failed:
                return None
            active_deadline = now + timedelta(seconds=settings.active_job_deadline_seconds)
            if row["active_deadline_at"]:
                active_deadline = datetime.fromisoformat(row["active_deadline_at"])
                if row["next_attempt_at"]:
                    lateness = max(0, (now - datetime.fromisoformat(row["next_attempt_at"])).total_seconds())
                    active_deadline += timedelta(seconds=lateness)
            conn.execute(
                """UPDATE jobs SET status = 'running', phase = 'resolving', worker_id = ?, claimed_at = ?,
                   started_at = COALESCE(started_at, ?),
                   active_deadline_at = ?, next_attempt_at = NULL,
                   progress_json = NULL, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND status = 'queued' AND cancel_requested_at IS NULL""",
                (worker_id, utc_iso(now), utc_iso(now),
                 utc_iso(active_deadline), utc_iso(now), row["id"]),
            )
            return row["id"]
    finally:
        conn.close()
        if failed:
            remove_tree(job_workspace(settings, failed))


def _cancelled(settings: Settings, job_id: str) -> bool:
    conn = connect(settings)
    try:
        row = conn.execute("SELECT cancel_requested_at FROM jobs WHERE id = ? AND status = 'running'", (job_id,)).fetchone()
        # Loss of authoritative control is a stop condition, never permission.
        return row is None or bool(row["cancel_requested_at"])
    finally:
        conn.close()


def _finish_cancelled(settings: Settings, job_id: str) -> None:
    conn = connect(settings)
    now = utc_iso()
    remove_final = False
    try:
        with transaction(conn):
            row = conn.execute("SELECT status, file_state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            remove_final = row is None or row["file_state"] != "available"
            updated = conn.execute(
                """UPDATE jobs SET status = 'cancelled', phase = NULL, finished_at = ?, updated_at = ?,
                   revision = revision + 1, file_state = 'none', progress_json = NULL
                   WHERE id = ? AND status = 'running'""", (now, now, job_id),
            )
            if row is None or updated.rowcount == 1 or row["status"] not in {"queued", "running"}:
                release_reservation(conn, job_id)
    finally:
        conn.close()
        remove_tree(job_workspace(settings, job_id))
        if remove_final:
            remove_tree(job_final_dir(settings, job_id))


def _fail(settings: Settings, job_id: str, code: str, *, retryable: bool = False, retry_after: int | None = None) -> None:
    conn = connect(settings)
    now = utc_iso()
    remove_final = False
    body = {"code": code, "retryable": retryable}
    if retry_after is not None:
        body["retry_after_seconds"] = retry_after
    try:
        with transaction(conn):
            row = conn.execute("SELECT cancel_requested_at, status, file_state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            remove_final = row is None or row["file_state"] != "available"
            cancelled = bool(row and row["cancel_requested_at"])
            status = "cancelled" if cancelled else ("interrupted" if code == "INTERRUPTED" else "failed")
            updated = conn.execute(
                """UPDATE jobs SET status = ?, phase = NULL, error_json = ?, finished_at = ?, updated_at = ?,
                   progress_json = NULL, revision = revision + 1 WHERE id = ? AND status = 'running'""",
                (status, None if cancelled else json.dumps(body), now, now, job_id),
            )
            if row is None or updated.rowcount == 1 or row["status"] not in {"queued", "running"}:
                release_reservation(conn, job_id)
    finally:
        conn.close()
        remove_tree(job_workspace(settings, job_id))
        if remove_final:
            remove_tree(job_final_dir(settings, job_id))


def _progress(settings: Settings, job_id: str, event: dict) -> None:
    # Replace phase progress instead of merging old speed/ETA into a new phase.
    progress = {key: value for key, value in event.items() if key != "type"}
    for key in ("downloaded_bytes", "total_bytes", "speed_bps", "speed_bytes_per_second", "eta_seconds", "percent"):
        value = progress.get(key)
        if value is not None and (not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0):
            progress[key] = None
    conn = connect(settings)
    try:
        updated = conn.execute(
            """UPDATE jobs SET phase = ?, progress_json = ?, revision = revision + 1, updated_at = ?
               WHERE id = ? AND status = 'running'""",
            (event.get("phase"), json.dumps(progress, allow_nan=False), utc_iso(), job_id),
        )
        if updated.rowcount != 1:
            raise AppError("INTERRUPTED", 409)
    finally:
        conn.close()


def _runtime_budgets(settings: Settings, work: Path, output: Path) -> None:
    """Actual on-disk bytes, independent of provider totals/progress callbacks."""
    workspace = 0
    inputs = 0
    output_bytes = 0
    seen: set[tuple[int, int]] = set()
    for item in work.rglob("*"):
        if item.is_symlink():
            raise AppError("OUTPUT_INVALID", 500)
        try:
            if not item.is_file():
                continue
            stat = item.stat()
        except FileNotFoundError:  # concurrent rename of .part to input
            continue
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        workspace += stat.st_size
        if item == output:
            output_bytes += stat.st_size
        elif not item.name.startswith("ffmpeg."):
            inputs += stat.st_size
    if inputs > settings.max_input_bytes or output_bytes > settings.max_output_bytes or workspace > settings.max_workspace_bytes:
        raise AppError("LIMIT_EXCEEDED", 413)
    if directory_size(settings.data_dir) > settings.max_storage_bytes or free_bytes(settings) < settings.min_free_bytes:
        raise AppError("STORAGE_FULL", 507)


def _schedule_retry(settings: Settings, job_id: str, code: str, seconds: int) -> None:
    conn = connect(settings)
    try:
        with transaction(conn):
            current = conn.execute("SELECT active_deadline_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
            deadline = None
            if current and current["active_deadline_at"]:
                deadline = utc_iso(datetime.fromisoformat(current["active_deadline_at"]) + timedelta(seconds=seconds))
            updated = conn.execute(
                """UPDATE jobs SET status = 'queued', phase = 'retry_wait', next_attempt_at = ?, active_deadline_at = ?,
                   progress_json = NULL, revision = revision + 1, updated_at = ?, error_json = ?
                   WHERE id = ? AND status = 'running' AND cancel_requested_at IS NULL""",
                (utc_iso(utc_now() + timedelta(seconds=seconds)), deadline, utc_iso(),
                 json.dumps({"code": code, "retryable": True, "retry_after_seconds": seconds}), job_id),
            )
    finally:
        conn.close()
    if updated.rowcount != 1:
        _finish_cancelled(settings, job_id)
    else:
        remove_tree(job_workspace(settings, job_id))


def process_job(settings: Settings, job_id: str, stop_event: threading.Event | None = None) -> None:
    conn = connect(settings)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        cooldown = _cooldown_seconds(conn)
    finally:
        conn.close()
    if row is None or row["status"] != "running":
        return
    if row["cancel_requested_at"]:
        _finish_cancelled(settings, job_id)
        return
    if cooldown:
        _schedule_retry(settings, job_id, "SOURCE_RATE_LIMITED", cooldown)
        return
    contract = json.loads(row["contract_json"])
    source = json.loads(row["source_json"])
    work = job_workspace(settings, job_id)
    remove_tree(work)
    work.mkdir(parents=True, exist_ok=True)
    output = work / f"final.{contract.get('ext') or 'bin'}"
    attempts = int(row["attempts_used"] or 0) + 1
    deadline = datetime.fromisoformat(row["active_deadline_at"])
    remaining = int((deadline - utc_now()).total_seconds())
    if remaining <= 0:
        _fail(settings, job_id, "JOB_TIMEOUT", retryable=True)
        return
    conn = connect(settings)
    try:
        conn.execute(
            """UPDATE jobs SET attempts_used = ?, phase = 'resolving', progress_json = NULL,
               revision = revision + 1, updated_at = ? WHERE id = ? AND status = 'running'""",
            (attempts, utc_iso(), job_id),
        )
    finally:
        conn.close()
    payload = {
        "action": "job", "url": source["canonical_url"], "video_id": source["video_id"],
        "adapter": settings.media_adapter, "catalog": str(settings.fixture_catalog) if settings.fixture_catalog else None,
        "allow_test_hooks": settings.allow_test_hooks, "ffmpeg": settings.ffmpeg_path,
        "ffprobe": settings.ffprobe_path, "deno": settings.deno_path, "contract": contract,
        "work_dir": str(work), "output_path": str(output), "manage_slot": True,
        "native_cap": settings.native_mp4_cap, "ffmpeg_timeout": remaining,
        "max_source_duration_seconds": settings.max_source_duration_seconds,
        "analysis_deadline_seconds": settings.analysis_deadline_seconds,
    }
    try:
        outcome = execute(
            payload, settings, on_event=lambda event: _progress(settings, job_id, event),
            should_cancel=lambda: bool(stop_event and stop_event.is_set()) or _cancelled(settings, job_id),
            watchdog=lambda: _runtime_budgets(settings, work, output), deadline_seconds=max(1, remaining),
        )
    except AppError as exc:
        _fail(settings, job_id, exc.code, retryable=exc.retryable)
        return
    if stop_event and stop_event.is_set():
        _fail(settings, job_id, "INTERRUPTED", retryable=True)
        return
    if outcome["status"] == "cancelled" or _cancelled(settings, job_id):
        _finish_cancelled(settings, job_id)
        return
    if outcome["status"] == "timeout":
        _fail(settings, job_id, "JOB_TIMEOUT", retryable=True)
        return
    if outcome["status"] == "ok":
        try:
            _runtime_budgets(settings, work, output)
            _progress(settings, job_id, {"type": "progress", "phase": "verifying"})
            # ffprobe validation runs inside the owned engine group. Reusing
            # its checked facts avoids an unsupervised duplicate subprocess
            # during publication/shutdown.
            checked = outcome.get("result", {}).get("checked")
            if not isinstance(checked, dict) or checked.get("bytes") != output.stat().st_size:
                raise AppError("OUTPUT_INVALID", 500)
            _publish_success(settings, job_id, output, source, contract, checked)
        except AppError as exc:
            _fail(settings, job_id, exc.code, retryable=exc.retryable)
        return
    error = outcome.get("error") or {}
    code = error.get("code") or "ENGINE_ERROR"
    retry_after = int(error.get("retry_after") or error.get("retry_after_seconds") or 120)
    if code == "SOURCE_RATE_LIMITED":
        conn = connect(settings)
        try:
            set_cooldown(conn, retry_after, "download")
        finally:
            conn.close()
    if code == "HTTP_403":
        if row["refresh_403_used"]:
            _fail(settings, job_id, "SOURCE_FORBIDDEN")
            return
        conn = connect(settings)
        try:
            conn.execute("UPDATE jobs SET refresh_403_used = 1 WHERE id = ?", (job_id,))
        finally:
            conn.close()
        _schedule_retry(settings, job_id, code, 1)
        return
    retryable = bool(error.get("retryable")) or code == "SOURCE_RATE_LIMITED"
    if code in NON_RETRYABLE or not retryable or attempts >= settings.max_auto_retries + 1:
        _fail(settings, job_id, code, retryable=retryable, retry_after=retry_after if code == "SOURCE_RATE_LIMITED" else None)
        return
    backoff = min(300, 2 ** attempts + random.randint(0, max(1, attempts)))
    _schedule_retry(settings, job_id, code, max(retry_after, backoff) if code == "SOURCE_RATE_LIMITED" else backoff)


def directory_bytes(path: Path) -> int:
    from app.services.storage import directory_size

    return directory_size(path)


def _publish_success(settings: Settings, job_id: str, output: Path, source: dict, contract: dict, checked: dict) -> None:
    conn = connect(settings)
    published = False
    preserve_final = False
    try:
        with transaction(conn):
            row = conn.execute("SELECT status, cancel_requested_at, keep_on_server, file_state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            preserve_final = bool(row and row["file_state"] == "available")
            if row is None or row["status"] != "running" or row["cancel_requested_at"]:
                if row and row["status"] == "running":
                    conn.execute("UPDATE jobs SET status = 'cancelled', phase = NULL, finished_at = ?, updated_at = ?, revision = revision + 1 WHERE id = ?", (utc_iso(), utc_iso(), job_id))
                release_reservation(conn, job_id)
                return
            _runtime_budgets(settings, job_workspace(settings, job_id), output)
            filename = safe_download_name(source.get("title") or "video", contract.get("ext") or "bin", job_id)
            final = publish_file(settings, job_id, output, filename)
            artifact = {
                "bytes": checked["bytes"], "filename": filename,
                "mime": contract.get("mime") or "application/octet-stream",
                "relative_path": str(final.relative_to(settings.data_dir)), "duration": checked.get("duration"),
                "media": {key: value for key, value in checked.items() if key not in {"bytes", "duration"}},
            }
            now = utc_now()
            expires = None if row["keep_on_server"] else utc_iso(now + timedelta(seconds=settings.file_ttl_seconds))
            conn.execute(
                """UPDATE jobs SET status = 'succeeded', phase = NULL, file_state = 'available', artifact_json = ?,
                   file_expires_at = ?, finished_at = ?, updated_at = ?, revision = revision + 1,
                   progress_json = NULL, error_json = NULL WHERE id = ? AND status = 'running'""",
                (json.dumps(artifact), expires, utc_iso(now), utc_iso(now), job_id),
            )
            release_reservation(conn, job_id)
        published = True
    finally:
        conn.close()
        remove_tree(job_workspace(settings, job_id))
        if not published and not preserve_final:
            remove_tree(job_final_dir(settings, job_id))


def serve_forever(settings: Settings, stop_event: threading.Event | None = None) -> None:
    validate_limits(settings)
    init_db(settings).close()
    lock = acquire_worker_lock(settings)
    worker_id = _worker_id(settings)
    stopping = stop_event or threading.Event()
    old_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, lambda *_: stopping.set())
    future: Future | None = None
    job_id: str | None = None
    last_beat = last_housekeeping = float("-inf")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-job")
    try:
        reconcile_abandoned(settings)
        while not stopping.is_set():
            now = time.monotonic()
            if now - last_beat >= HEARTBEAT_INTERVAL_SECONDS:
                beat(settings, worker_id)
                last_beat = now
            if now - last_housekeeping >= HOUSEKEEPING_INTERVAL_SECONDS:
                conn = connect(settings)
                try:
                    expire_finished_files(conn, settings)
                    prune_old_history(conn, settings)
                finally:
                    conn.close()
                last_housekeeping = now
            if future and future.done():
                try:
                    future.result()
                except Exception:
                    traceback.print_exc()
                    if job_id:
                        _fail(settings, job_id, "ENGINE_ERROR", retryable=True)
                future, job_id = None, None
            if future is None:
                job_id = claim_next(settings, worker_id)
                if job_id:
                    future = executor.submit(process_job, settings, job_id, stopping)
            stopping.wait(CONTROL_INTERVAL_SECONDS)
    finally:
        stopping.set()
        try:
            # Keep cancellation alive if a DB/control callback failed.
            try:
                stop_owned_engines()
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            if job_id:
                conn = connect(settings)
                try:
                    active = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
                finally:
                    conn.close()
                if active and active["status"] == "running":
                    _fail(settings, job_id, "INTERRUPTED", retryable=True)
        finally:
            # A failing final DB update must never retain exclusive ownership.
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            lock.close()


def main() -> None:
    serve_forever(load_settings())


if __name__ == "__main__":
    main()
