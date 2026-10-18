"""Managed paths, quotas, filenames, and expiry."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import transaction, utc_iso, utc_now
from app.errors import AppError

RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def ensure_dirs(settings: Settings) -> None:
    for path in (settings.data_dir, settings.db_path.parent, settings.tmp_dir, settings.files_dir, settings.log_dir):
        path.mkdir(parents=True, exist_ok=True)


def safe_download_name(title: str, ext: str, job_id: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "", title or "").strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned.upper() in RESERVED or re.fullmatch(r"(COM|LPT)\d", cleaned.upper() or ""):
        cleaned = f"_{cleaned}"
    if not cleaned:
        cleaned = "video"
    cleaned = cleaned[:80]
    suffix = re.sub(r"[^A-Za-z0-9]", "", job_id)[:8] or "file"
    extension = re.sub(r"[^a-z0-9]", "", ext.lower()) or "bin"
    return f"{cleaned}-{suffix}.{extension}"


def job_workspace(settings: Settings, job_id: str) -> Path:
    path = (settings.tmp_dir / job_id).resolve()
    _contained(settings.tmp_dir, path)
    return path


def job_final_dir(settings: Settings, job_id: str) -> Path:
    path = (settings.files_dir / job_id).resolve()
    _contained(settings.files_dir, path)
    return path


def _contained(root: Path, path: Path) -> Path:
    root_r = root.resolve()
    if path.is_symlink():
        raise AppError("BAD_REQUEST", 400)
    resolved = path.resolve()
    if resolved != root_r and root_r not in resolved.parents:
        raise AppError("BAD_REQUEST", 400)
    return resolved


def assert_contained(root: Path, path: Path) -> Path:
    return _contained(root, path)


def directory_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not (Path(dirpath) / name).is_symlink()]
        for name in filenames:
            file_path = Path(dirpath) / name
            if file_path.is_symlink():
                continue
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return total


def managed_bytes(settings: Settings) -> int:
    return directory_size(settings.files_dir) + directory_size(settings.tmp_dir)


def free_bytes(settings: Settings) -> int:
    usage = shutil.disk_usage(settings.data_dir)
    return int(usage.free)


def publish_file(settings: Settings, job_id: str, staged: Path, download_name: str) -> Path:
    """Atomically publish a staged file that already lives on the data volume."""
    if staged.is_symlink() or not staged.is_file():
        raise AppError("OUTPUT_INVALID", 500)
    final_dir = job_final_dir(settings, job_id)
    final_dir.mkdir(parents=True, exist_ok=True)
    target = final_dir / "output"
    # Keep the extension beside the opaque internal name.
    ext = Path(download_name).suffix.lower()
    target = final_dir / f"output{ext}"
    assert_contained(settings.files_dir, target)
    if target.exists() or target.is_symlink():
        target.unlink()
    os.replace(staged, target)
    return target


def remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def active_leases(conn: sqlite3.Connection, job_id: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM transfer_leases WHERE job_id = ? AND expires_at > ?",
        (job_id, utc_iso()),
    ).fetchone()
    return bool(row and row["c"])


def expire_finished_files(conn: sqlite3.Connection, settings: Settings) -> int:
    """Expire unretained files. Never deletes kept files. Skips active transfers."""
    now = utc_iso()
    removed = 0
    with transaction(conn):
        rows = conn.execute(
            """
            SELECT id, artifact_json FROM jobs
            WHERE file_state = 'available'
              AND keep_on_server = 0
              AND file_expires_at IS NOT NULL
              AND file_expires_at <= ?
            """,
            (now,),
        ).fetchall()
        for row in rows:
            if active_leases(conn, row["id"]):
                continue
            conn.execute(
                """
                UPDATE jobs
                SET file_state = 'expired', artifact_json = NULL, revision = revision + 1, updated_at = ?
                WHERE id = ? AND file_state = 'available' AND keep_on_server = 0
                """,
                (now, row["id"]),
            )
            removed += 1
    for row in rows:
        final = job_final_dir(settings, row["id"])
        if final.exists():
            # Re-check the committed state so a pin that won the race is kept.
            current = conn.execute("SELECT file_state, keep_on_server FROM jobs WHERE id = ?", (row["id"],)).fetchone()
            if current and current["file_state"] == "expired" and not current["keep_on_server"]:
                remove_tree(final)
    return removed


def prune_history(conn: sqlite3.Connection) -> int:
    settings_row = None
    del settings_row
    return 0


def prune_old_history(conn: sqlite3.Connection, settings: Settings) -> int:
    from datetime import timedelta

    cutoff = utc_iso(utc_now() - timedelta(seconds=settings.history_retention_seconds))
    with transaction(conn):
        cur = conn.execute(
            """
            DELETE FROM jobs
            WHERE created_at < ?
              AND file_state != 'available'
              AND status IN ('succeeded', 'failed', 'cancelled', 'interrupted')
            """,
            (cutoff,),
        )
        return cur.rowcount or 0


def ensure_space(conn: sqlite3.Connection, settings: Settings, estimated: int | None) -> None:
    expire_finished_files(conn, settings)
    used = managed_bytes(settings)
    reserve = estimated if estimated is not None else settings.max_output_bytes
    if used + reserve > settings.max_storage_bytes:
        raise AppError("STORAGE_FULL", 507, retryable=False)
    if free_bytes(settings) < settings.min_free_bytes + min(reserve, settings.max_output_bytes):
        raise AppError("STORAGE_FULL", 507, retryable=False)
    if estimated is not None and estimated > settings.max_output_bytes:
        raise AppError("LIMIT_EXCEEDED", 413, retryable=False)
