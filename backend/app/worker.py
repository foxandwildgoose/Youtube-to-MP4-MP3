"""Dedicated job worker. One exclusive owner, short SQLite claims."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from app.config import Settings, load_settings, validate_limits
from app.db import connect, init_db, transaction, utc_iso, utc_now
from app.engine_runner import execute
from app.errors import AppError
from app.services.analysis import set_cooldown
from app.services.media_validate import validate_output
from app.services.storage import (
    ensure_dirs,
    expire_finished_files,
    job_final_dir,
    job_workspace,
    prune_old_history,
    publish_file,
    remove_tree,
    safe_download_name,
)

NON_RETRYABLE = {
    "SOURCE_AUTH_REQUIRED",
    "SOURCE_FORBIDDEN",
    "SOURCE_UNAVAILABLE",
    "FORMAT_CHANGED",
    "FORMAT_UNAVAILABLE",
    "OUTPUT_INVALID",
    "POSTPROCESS_FAILED",
    "DEPENDENCY_MISSING",
    "STORAGE_FULL",
    "LIMIT_EXCEEDED",
    "CONSENT_REQUIRED",
    "TRANSCODING_DISABLED",
}


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
    """Mark running jobs interrupted. Call only after this process holds the worker lock."""
    conn = connect(settings)
    now = utc_iso()
    try:
        rows = conn.execute("SELECT id FROM jobs WHERE status = 'running'").fetchall()
        with transaction(conn):
            for row in rows:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'interrupted', phase = NULL, finished_at = ?, updated_at = ?,
                        revision = revision + 1,
                        error_json = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (
                        now,
                        now,
                        json.dumps({"code": "INTERRUPTED", "retryable": True}),
                        row["id"],
                    ),
                )
    finally:
        conn.close()
    for row in rows:
        remove_tree(job_workspace(settings, row["id"]))
        current = connect(settings)
        try:
            state = current.execute("SELECT file_state FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        finally:
            current.close()
        if state and state["file_state"] != "available":
            remove_tree(job_final_dir(settings, row["id"]))
    return len(rows)


def beat(settings: Settings, worker_id: str) -> None:
    conn = connect(settings)
    try:
        now = utc_iso()
        conn.execute(
            """
            INSERT INTO worker_heartbeat (id, worker_id, beat_at, pid) VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET worker_id = excluded.worker_id, beat_at = excluded.beat_at, pid = excluded.pid
            """,
            (worker_id, now, os.getpid()),
        )
    finally:
        conn.close()


def claim_next(settings: Settings, worker_id: str) -> str | None:
    conn = connect(settings)
    try:
        with transaction(conn):
            running = conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE status = 'running'").fetchone()["c"]
            if running >= settings.media_concurrency:
                return None
            row = conn.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'queued' AND cancel_requested_at IS NULL
                ORDER BY created_at LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = 'running', phase = 'resolving', worker_id = ?, claimed_at = ?,
                    started_at = COALESCE(started_at, ?), active_deadline_at = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND status = 'queued' AND cancel_requested_at IS NULL
                """,
                (
                    worker_id,
                    utc_iso(now),
                    utc_iso(now),
                    utc_iso(now + timedelta(seconds=settings.active_job_deadline_seconds)),
                    utc_iso(now),
                    row["id"],
                ),
            )
            if cur.rowcount != 1:
                return None
            return row["id"]
    finally:
        conn.close()


def _cancelled(settings: Settings, job_id: str) -> bool:
    conn = connect(settings)
    try:
        row = conn.execute("SELECT cancel_requested_at FROM jobs WHERE id = ? AND status = 'running'", (job_id,)).fetchone()
        return bool(row and row["cancel_requested_at"])
    finally:
        conn.close()


def _finish_cancelled(settings: Settings, job_id: str) -> None:
    conn = connect(settings)
    now = utc_iso()
    try:
        with transaction(conn):
            conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', phase = NULL, finished_at = ?, updated_at = ?,
                    revision = revision + 1, file_state = 'none'
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job_id),
            )
    finally:
        conn.close()
    remove_tree(job_workspace(settings, job_id))
    remove_tree(job_final_dir(settings, job_id))


def _fail(settings: Settings, job_id: str, code: str, *, retryable: bool = False, retry_after: int | None = None) -> None:
    conn = connect(settings)
    now = utc_iso()
    body = {"code": code, "retryable": retryable}
    if retry_after is not None:
        body["retry_after_seconds"] = retry_after
    try:
        with transaction(conn):
            row = conn.execute("SELECT cancel_requested_at, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row and row["status"] == "running" and row["cancel_requested_at"]:
                conn.execute(
                    """
                    UPDATE jobs SET status = 'cancelled', phase = NULL, finished_at = ?, updated_at = ?, revision = revision + 1
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', phase = NULL, error_json = ?, finished_at = ?, updated_at = ?, revision = revision + 1
                    WHERE id = ? AND status = 'running'
                    """,
                    (json.dumps(body), now, now, job_id),
                )
    finally:
        conn.close()
    remove_tree(job_workspace(settings, job_id))


def _progress(settings: Settings, job_id: str, event: dict) -> None:
    conn = connect(settings)
    try:
        conn.execute(
            """
            UPDATE jobs
            SET phase = ?, progress_json = ?, revision = revision + 1, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (event.get("phase"), json.dumps({k: v for k, v in event.items() if k != "type"}), utc_iso(), job_id),
        )
    finally:
        conn.close()


def process_job(settings: Settings, job_id: str) -> None:
    conn = connect(settings)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row["status"] != "running":
        return
    if row["cancel_requested_at"]:
        _finish_cancelled(settings, job_id)
        return
    contract = json.loads(row["contract_json"])
    source = json.loads(row["source_json"])
    work = job_workspace(settings, job_id)
    remove_tree(work)
    work.mkdir(parents=True, exist_ok=True)
    output = work / f"final.{contract.get('ext') or 'bin'}"
    attempts = int(row["attempts_used"] or 0)
    refreshed_403 = False
    max_attempts = settings.max_auto_retries + 1
    while attempts < max_attempts:
        if _cancelled(settings, job_id):
            _finish_cancelled(settings, job_id)
            return
        deadline = datetime.fromisoformat(row["active_deadline_at"])
        remaining = int((deadline - utc_now()).total_seconds())
        if remaining <= 0:
            _fail(settings, job_id, "JOB_TIMEOUT", retryable=True)
            return
        attempts += 1
        conn = connect(settings)
        try:
            conn.execute("UPDATE jobs SET attempts_used = ?, phase = 'resolving', updated_at = ? WHERE id = ?", (attempts, utc_iso(), job_id))
        finally:
            conn.close()
        payload = {
            "action": "job",
            "url": source["canonical_url"],
            "video_id": source["video_id"],
            "adapter": settings.media_adapter,
            "catalog": str(settings.fixture_catalog) if settings.fixture_catalog else None,
            "allow_test_hooks": settings.allow_test_hooks,
            "ffmpeg": settings.ffmpeg_path,
            "ffprobe": settings.ffprobe_path,
            "deno": settings.deno_path,
            "contract": contract,
            "work_dir": str(work),
            "output_path": str(output),
            "manage_slot": True,
            "native_cap": settings.native_mp4_cap,
            "ffmpeg_timeout": min(remaining, settings.active_job_deadline_seconds),
        }
        try:
            used = directory_bytes(work)
            if used > settings.max_workspace_bytes:
                _fail(settings, job_id, "LIMIT_EXCEEDED")
                return
        except OSError:
            pass
        outcome = execute(
            payload,
            settings,
            on_event=lambda event: _progress(settings, job_id, event),
            should_cancel=lambda: _cancelled(settings, job_id),
            deadline_seconds=max(1, remaining),
        )
        if outcome["status"] == "cancelled" or _cancelled(settings, job_id):
            _finish_cancelled(settings, job_id)
            return
        if outcome["status"] == "timeout":
            _fail(settings, job_id, "JOB_TIMEOUT", retryable=True)
            return
        if outcome["status"] == "ok":
            try:
                checked = validate_output(settings, output, contract)
            except AppError as exc:
                _fail(settings, job_id, exc.code, retryable=exc.retryable)
                return
            _publish_success(settings, job_id, output, source, contract, checked)
            return
        error = outcome.get("error") or {}
        code = error.get("code") or "ENGINE_ERROR"
        if code == "HTTP_403":
            if refreshed_403:
                _fail(settings, job_id, "SOURCE_FORBIDDEN")
                return
            refreshed_403 = True
            continue
        if code == "SOURCE_RATE_LIMITED":
            conn = connect(settings)
            try:
                set_cooldown(conn, int(error.get("retry_after") or 120), "download")
            finally:
                conn.close()
            _fail(settings, job_id, "SOURCE_RATE_LIMITED", retryable=True, retry_after=int(error.get("retry_after") or 120))
            return
        if code in NON_RETRYABLE or not error.get("retryable") or attempts >= max_attempts:
            _fail(settings, job_id, code if code in NON_RETRYABLE or code else "ENGINE_ERROR", retryable=bool(error.get("retryable")))
            return
    _fail(settings, job_id, "ENGINE_ERROR", retryable=True)


def directory_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


def _publish_success(settings: Settings, job_id: str, output: Path, source: dict, contract: dict, checked: dict) -> None:
    filename = safe_download_name(source.get("title") or "video", contract.get("ext") or "bin", job_id)
    published = publish_file(settings, job_id, output, filename)
    artifact = {
        "bytes": checked["bytes"],
        "filename": filename,
        "mime": contract.get("mime") or "application/octet-stream",
        "relative_path": str(published.relative_to(settings.data_dir)),
        "duration": checked.get("duration"),
    }
    conn = connect(settings)
    now = utc_now()
    try:
        with transaction(conn):
            row = conn.execute("SELECT status, cancel_requested_at, keep_on_server FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None or row["status"] != "running":
                remove_tree(job_final_dir(settings, job_id))
                return
            if row["cancel_requested_at"]:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', phase = NULL, finished_at = ?, updated_at = ?, revision = revision + 1, file_state = 'none'
                    WHERE id = ? AND status = 'running'
                    """,
                    (utc_iso(now), utc_iso(now), job_id),
                )
                remove_tree(job_final_dir(settings, job_id))
                return
            expires = None if row["keep_on_server"] else utc_iso(now + timedelta(seconds=settings.file_ttl_seconds))
            conn.execute(
                """
                UPDATE jobs
                SET status = 'succeeded', phase = NULL, file_state = 'available', artifact_json = ?,
                    file_expires_at = ?, finished_at = ?, updated_at = ?, revision = revision + 1, progress_json = NULL
                WHERE id = ? AND status = 'running' AND cancel_requested_at IS NULL
                """,
                (json.dumps(artifact), expires, utc_iso(now), utc_iso(now), job_id),
            )
    finally:
        conn.close()
    remove_tree(job_workspace(settings, job_id))


def serve_forever(settings: Settings) -> None:
    validate_limits(settings)
    init_db(settings)
    lock = acquire_worker_lock(settings)
    worker_id = _worker_id(settings)
    try:
        reconcile_abandoned(settings)
        while True:
            beat(settings, worker_id)
            conn = connect(settings)
            try:
                expire_finished_files(conn, settings)
                prune_old_history(conn, settings)
            finally:
                conn.close()
            job_id = claim_next(settings, worker_id)
            if not job_id:
                time.sleep(0.4)
                continue
            try:
                process_job(settings, job_id)
            except Exception:
                traceback.print_exc()
                _fail(settings, job_id, "ENGINE_ERROR", retryable=True)
    finally:
        lock.close()


def main() -> None:
    settings = load_settings()
    serve_forever(settings)


if __name__ == "__main__":
    main()
