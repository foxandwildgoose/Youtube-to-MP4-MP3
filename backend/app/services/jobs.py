"""Job records, snapshots, and file-state transitions."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.db import transaction, utc_iso, utc_now
from app.errors import AppError
from app.services.analysis import load_analysis
from app.services.storage import active_leases, expire_finished_files, job_final_dir, remove_tree, reserve_job, release_reservation


ACTIVE_STATUSES = {"queued", "running"}
RETRY_STATUSES = {"failed", "cancelled", "interrupted"}


def validate_retry_parent(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    """Retry repairs terminal unsuccessful work; redownload is an ordinary create."""
    parent = conn.execute("SELECT * FROM jobs WHERE id = ? AND history_hidden = 0", (job_id,)).fetchone()
    if parent is None:
        raise AppError("NOT_FOUND", 404)
    if parent["status"] not in RETRY_STATUSES:
        raise AppError("RETRY_NOT_ALLOWED", 409)
    return parent


def create_job(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    analysis_id: str,
    choice_id: str,
    keep_on_server: bool,
    conversion_consent: bool,
    idempotency_key: str,
    request_hash: str,
    parent_job_id: str | None = None,
) -> dict[str, Any]:
    job_id = secrets.token_hex(16)
    now = utc_iso()
    with transaction(conn):
        again = conn.execute("SELECT request_hash, job_id FROM idempotency_keys WHERE key = ?", (idempotency_key,)).fetchone()
        if again:
            if again["request_hash"] != request_hash or not again["job_id"]:
                raise AppError("IDEMPOTENCY_CONFLICT", 409)
            present = conn.execute("SELECT history_hidden FROM jobs WHERE id = ?", (again["job_id"],)).fetchone()
            if present is None or present["history_hidden"]:
                raise AppError("IDEMPOTENCY_CONFLICT", 409)
            return snapshot(conn, again["job_id"])
        analysis = load_analysis(conn, analysis_id, require_fresh=True)
        if parent_job_id:
            parent = conn.execute("SELECT * FROM jobs WHERE id = ? AND history_hidden = 0", (parent_job_id,)).fetchone()
            if parent is None:
                raise AppError("NOT_FOUND", 404)
            if json.loads(parent["source_json"]).get("video_id") != analysis["video_id"]:
                raise AppError("PARENT_MISMATCH", 409)
            validate_retry_parent(conn, parent_job_id)
        choice = next((item for item in analysis["choices"] if item["choice_id"] == choice_id), None)
        if choice is None:
            raise AppError("FORMAT_UNAVAILABLE", 409)
        contract = choice["contract"]
        if contract.get("requires_consent") and not conversion_consent:
            raise AppError("CONSENT_REQUIRED", 409)
        if contract.get("conversion") and not settings.enable_transcoding:
            raise AppError("TRANSCODING_DISABLED", 409)
        waiting = conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE status = 'queued'").fetchone()["c"]
        if waiting >= settings.max_waiting_jobs:
            raise AppError("LIMIT_EXCEEDED", 429, retryable=True, retry_after=5)
        expire_finished_files(conn, settings)
        source = {
            "video_id": analysis["video_id"],
            "canonical_url": analysis["canonical_url"],
            "title": analysis["metadata"].get("title"),
            "channel": analysis["metadata"].get("channel"),
            "duration_seconds": analysis["metadata"].get("duration_seconds"),
        }
        conn.execute(
            """
            INSERT INTO jobs (
              id, parent_job_id, analysis_id, status, phase, file_state, keep_on_server, revision,
              contract_json, source_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', NULL, 'none', ?, 1, ?, ?, ?, ?)
            """,
            (
                job_id,
                parent_job_id,
                analysis_id,
                1 if keep_on_server else 0,
                json.dumps(contract),
                json.dumps(source),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO idempotency_keys (key, request_hash, job_id, created_at) VALUES (?, ?, ?, ?)",
            (idempotency_key, request_hash, job_id, now),
        )
        reserve_job(conn, settings, job_id, contract)
    return snapshot(conn, job_id)


def snapshot(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None or row["history_hidden"]:
        raise AppError("NOT_FOUND", 404)
    source = json.loads(row["source_json"])
    contract = json.loads(row["contract_json"])
    progress = json.loads(row["progress_json"]) if row["progress_json"] else None
    error = json.loads(row["error_json"]) if row["error_json"] else None
    artifact = json.loads(row["artifact_json"]) if row["artifact_json"] else None
    position = None
    if row["status"] == "queued":
        position = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status = 'queued' AND (created_at < ? OR (created_at = ? AND id < ?))",
            (row["created_at"], row["created_at"], job_id),
        ).fetchone()["c"] + 1
    if artifact:
        artifact = {
            "bytes": artifact.get("bytes"),
            "filename": artifact.get("filename"),
            "mime": artifact.get("mime"),
            "expires_at": row["file_expires_at"],
            "duration_seconds": artifact.get("duration"),
            "media": artifact.get("media"),
        }
    return {
        "id": row["id"],
        "revision": row["revision"],
        "status": row["status"],
        "phase": row["phase"],
        "cancel_requested": bool(row["cancel_requested_at"]),
        "queue_position": position,
        "file_state": row["file_state"],
        "keep_on_server": bool(row["keep_on_server"]),
        "progress": progress,
        "error": error,
        "source": source,
        "output": {
            "kind": contract.get("kind"),
            "label": contract.get("label"),
            "container": contract.get("container"),
            "conversion_required": bool(contract.get("conversion")),
            "width": contract.get("output_width"),
            "height": contract.get("output_height"),
            "fps": contract.get("output_fps"),
            "bitrate_kbps": contract.get("mp3_bitrate"),
            "audio_track": contract.get("audio_track_key"),
            "audio_language": contract.get("audio_language"),
            "audio_role": contract.get("audio_role"),
            "video_codec": contract.get("output_vcodec"),
            "audio_codec": contract.get("output_acodec"),
            "size_estimate": contract.get("size_estimate"),
            "size_is_estimate": contract.get("size_is_estimate"),
            "size_provenance": contract.get("output_size_provenance"),
        },
        "artifact": artifact,
        "parent_job_id": row["parent_job_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "next_attempt_at": row["next_attempt_at"],
        "attempts_used": row["attempts_used"],
        "retry_allowed": row["status"] in RETRY_STATUSES,
    }


def list_jobs(conn: sqlite3.Connection, *, status: str | None = None, limit: int = 30, offset: int = 0, search: str | None = None, format: str | None = None, active: bool | None = None, file_state: str | None = None) -> dict[str, Any]:
    clauses = ["history_hidden = 0"]
    args: list[Any] = []
    if status:
        clauses.append("status = ?")
        args.append(status)
    if active is not None:
        clauses.append("status IN ('queued', 'running')" if active else "status NOT IN ('queued', 'running')")
    if format:
        clauses.append("json_extract(contract_json, '$.kind') = ?")
        args.append(format)
    if file_state:
        clauses.append("file_state = ?")
        args.append(file_state)
    if search:
        clauses.append("(COALESCE(json_extract(source_json, '$.title'), '') LIKE ? ESCAPE '\\' OR COALESCE(json_extract(source_json, '$.channel'), '') LIKE ? ESCAPE '\\' OR COALESCE(json_extract(source_json, '$.video_id'), '') LIKE ? ESCAPE '\\')")
        needle = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        args.extend([needle] * 3)
    where = " AND ".join(clauses)
    total = conn.execute(f"SELECT COUNT(*) AS c FROM jobs WHERE {where}", args).fetchone()["c"]
    rows = conn.execute(
        f"SELECT id FROM jobs WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return {"total": total, "offset": offset, "limit": limit, "jobs": [snapshot(conn, row["id"]) for row in rows]}


def request_cancel(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    now = utc_iso()
    with transaction(conn):
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", 404)
        if row["status"] == "queued":
            conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', finished_at = ?, revision = revision + 1, updated_at = ?, phase = NULL,
                    next_attempt_at = NULL, active_deadline_at = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            release_reservation(conn, job_id)
        elif row["status"] == "running":
            conn.execute(
                """
                UPDATE jobs
                SET cancel_requested_at = COALESCE(cancel_requested_at, ?), revision = revision + 1, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job_id),
            )
    return snapshot(conn, job_id)


def set_retention(conn: sqlite3.Connection, settings: Settings, job_id: str, keep: bool) -> dict[str, Any]:
    now = utc_now()
    with transaction(conn):
        row = conn.execute("SELECT file_state, finished_at, file_expires_at, keep_on_server FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", 404)
        if row["file_state"] != "available":
            raise AppError("FILE_EXPIRED" if row["file_state"] == "expired" else "FILE_MISSING", 410)
        if not row["keep_on_server"] and row["file_expires_at"] and row["file_expires_at"] <= utc_iso(now):
            raise AppError("FILE_EXPIRED", 410)
        expires = None if keep else utc_iso(now + timedelta(seconds=settings.file_ttl_seconds))
        conn.execute(
            """
            UPDATE jobs
            SET keep_on_server = ?, file_expires_at = ?, revision = revision + 1, updated_at = ?
            WHERE id = ? AND file_state = 'available'
            """,
            (1 if keep else 0, expires, utc_iso(now), job_id),
        )
    return snapshot(conn, job_id)


def delete_file(conn: sqlite3.Connection, settings: Settings, job_id: str) -> dict[str, Any]:
    with transaction(conn):
        row = conn.execute("SELECT file_state FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", 404)
        if active_leases(conn, job_id):
            raise AppError("LIMIT_EXCEEDED", 409, retryable=True, retry_after=2, extra={"message": "A download is in progress.", "action": "Wait for the download to finish, then delete the file."})
        if row["file_state"] not in {"available", "missing"}:
            return snapshot(conn, job_id)
        conn.execute(
            """
            UPDATE jobs
            SET file_state = 'deleted', artifact_json = NULL, keep_on_server = 0, file_expires_at = NULL,
                revision = revision + 1, updated_at = ?
            WHERE id = ?
            """,
            (utc_iso(), job_id),
        )
        remove_tree(job_final_dir(settings, job_id))
    return snapshot(conn, job_id)


def delete_history(conn: sqlite3.Connection, job_id: str) -> None:
    with transaction(conn):
        row = conn.execute("SELECT file_state, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return
        if row["status"] in ACTIVE_STATUSES:
            raise AppError("HISTORY_ACTIVE", 409)
        if row["file_state"] == "available":
            raise AppError("HISTORY_HAS_FILE", 409)
        conn.execute("UPDATE idempotency_keys SET job_id = NULL, expires_at = ? WHERE job_id = ?", (utc_iso(utc_now() + timedelta(days=7)), job_id))
        if conn.execute("SELECT 1 FROM jobs WHERE parent_job_id = ? LIMIT 1", (job_id,)).fetchone():
            conn.execute("UPDATE jobs SET history_hidden = 1, revision = revision + 1, updated_at = ? WHERE id = ?", (utc_iso(), job_id))
        else:
            conn.execute("DELETE FROM jobs WHERE id = ? AND file_state != 'available'", (job_id,))
