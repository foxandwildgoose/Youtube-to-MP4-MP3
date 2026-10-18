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
from app.services.storage import active_leases, ensure_space, job_final_dir, remove_tree


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
    existing = conn.execute("SELECT request_hash, job_id FROM idempotency_keys WHERE key = ?", (idempotency_key,)).fetchone()
    if existing:
        if existing["request_hash"] != request_hash:
            raise AppError("IDEMPOTENCY_CONFLICT", 409)
        if existing["job_id"]:
            return snapshot(conn, existing["job_id"])
        raise AppError("IDEMPOTENCY_CONFLICT", 409)
    analysis = load_analysis(conn, analysis_id, require_fresh=True)
    if parent_job_id:
        parent = conn.execute("SELECT source_json FROM jobs WHERE id = ?", (parent_job_id,)).fetchone()
        if parent is None:
            raise AppError("NOT_FOUND", 404)
        parent_source = json.loads(parent["source_json"])
        if parent_source.get("video_id") != analysis["video_id"]:
            raise AppError("PARENT_MISMATCH", 409)
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
    estimate = contract.get("size_estimate") if not contract.get("size_is_estimate") else None
    ensure_space(conn, settings, estimate if isinstance(estimate, int) else None)
    job_id = secrets.token_hex(16)
    now = utc_iso()
    source = {
        "video_id": analysis["video_id"],
        "canonical_url": analysis["canonical_url"],
        "title": analysis["metadata"].get("title"),
        "channel": analysis["metadata"].get("channel"),
        "duration_seconds": analysis["metadata"].get("duration_seconds"),
    }
    with transaction(conn):
        again = conn.execute("SELECT request_hash, job_id FROM idempotency_keys WHERE key = ?", (idempotency_key,)).fetchone()
        if again:
            if again["request_hash"] != request_hash or not again["job_id"]:
                raise AppError("IDEMPOTENCY_CONFLICT", 409)
            return snapshot(conn, again["job_id"])
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
            "SELECT COUNT(*) AS c FROM jobs WHERE status = 'queued' AND created_at < ?",
            (row["created_at"],),
        ).fetchone()["c"] + 1
    if artifact:
        artifact = {
            "bytes": artifact.get("bytes"),
            "filename": artifact.get("filename"),
            "mime": artifact.get("mime"),
            "expires_at": row["file_expires_at"],
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
        },
        "artifact": artifact,
        "parent_job_id": row["parent_job_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def list_jobs(conn: sqlite3.Connection, *, status: str | None, limit: int, offset: int) -> dict[str, Any]:
    clauses = ["history_hidden = 0"]
    args: list[Any] = []
    if status:
        clauses.append("status = ?")
        args.append(status)
    where = " AND ".join(clauses)
    total = conn.execute(f"SELECT COUNT(*) AS c FROM jobs WHERE {where}", args).fetchone()["c"]
    rows = conn.execute(
        f"SELECT id FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return {"total": total, "jobs": [snapshot(conn, row["id"]) for row in rows]}


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
                SET status = 'cancelled', finished_at = ?, revision = revision + 1, updated_at = ?, phase = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
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
        row = conn.execute("SELECT file_state, finished_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", 404)
        if row["file_state"] != "available":
            raise AppError("FILE_EXPIRED" if row["file_state"] == "expired" else "FILE_MISSING", 410)
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
        row = conn.execute("SELECT file_state FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", 404)
        if row["file_state"] == "available":
            raise AppError("HISTORY_HAS_FILE", 409)
        conn.execute("DELETE FROM jobs WHERE id = ? AND file_state != 'available'", (job_id,))
