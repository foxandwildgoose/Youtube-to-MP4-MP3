"""Managed paths, quotas, filenames, and expiry."""

from __future__ import annotations

import os
import json
import re
import secrets
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Any

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
    # Windows reserves device names even when followed by an extension.
    device_stem = cleaned.split('.', 1)[0].rstrip(' ').upper()
    if device_stem in RESERVED or re.fullmatch(r"(COM|LPT)\d", device_stem):
        cleaned = f"_{cleaned}"
    if not cleaned:
        cleaned = "video"
    cleaned = cleaned[:80]
    suffix = re.sub(r"[^A-Za-z0-9]", "", job_id)[:8] or "file"
    extension = re.sub(r"[^a-z0-9]", "", ext.lower()) or "bin"
    return f"{cleaned}-{suffix}.{extension}"


def job_workspace(settings: Settings, job_id: str) -> Path:
    _job_component(job_id)
    path = settings.tmp_dir / job_id
    _contained(settings.tmp_dir, path)
    return path


def job_final_dir(settings: Settings, job_id: str) -> Path:
    _job_component(job_id)
    path = settings.files_dir / job_id
    _contained(settings.files_dir, path)
    return path


def _contained(root: Path, path: Path) -> Path:
    root_r = root.absolute()
    raw = path.absolute()
    try:
        parts = raw.relative_to(root_r).parts
    except ValueError:
        raise AppError("BAD_REQUEST", 400)
    if any(part in {".", ".."} for part in parts) or root_r.is_symlink():
        raise AppError("BAD_REQUEST", 400)
    current = root_r
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AppError("BAD_REQUEST", 400)
    return raw


def _job_component(job_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise AppError("BAD_REQUEST", 400)


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
    """Actual volume bytes, including SQLite/WAL and bounded diagnostics."""
    return directory_size(settings.data_dir)


def free_bytes(settings: Settings) -> int:
    usage = shutil.disk_usage(settings.data_dir)
    return int(usage.free)


def publish_file(settings: Settings, job_id: str, staged: Path, download_name: str) -> Path:
    """Atomically publish a staged file that already lives on the data volume."""
    workspace = job_workspace(settings, job_id)
    assert_contained(workspace, staged)
    parts = staged.absolute().relative_to(workspace.absolute()).parts
    if not parts:
        raise AppError("OUTPUT_INVALID", 500)
    ext = Path(download_name).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
        raise AppError("OUTPUT_INVALID", 500)
    name = f"output{ext}"
    descriptors: list[int] = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptors.append(os.open(settings.data_dir, flags))
        root_fd = descriptors[-1]
        descriptors.append(os.open("tmp", flags, dir_fd=root_fd))
        for component in (job_id, *parts[:-1]):
            descriptors.append(os.open(component, flags, dir_fd=descriptors[-1]))
        source_dir = descriptors[-1]
        descriptors.append(os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=source_dir))
        staged_stat = os.fstat(descriptors[-1])
        if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
            raise AppError("OUTPUT_INVALID", 500)
        os.fsync(descriptors[-1])
        descriptors.append(os.open("files", flags, dir_fd=root_fd))
        files_fd = descriptors[-1]
        try:
            os.mkdir(job_id, mode=0o700, dir_fd=files_fd)
        except FileExistsError:
            pass
        descriptors.append(os.open(job_id, flags, dir_fd=files_fd))
        final_fd = descriptors[-1]
        os.replace(parts[-1], name, src_dir_fd=source_dir, dst_dir_fd=final_fd)
        published_stat = os.stat(name, dir_fd=final_fd, follow_symlinks=False)
        current_dir = os.stat(job_id, dir_fd=files_fd, follow_symlinks=False)
        actual_dir = os.fstat(final_fd)
        if ((published_stat.st_dev, published_stat.st_ino) != (staged_stat.st_dev, staged_stat.st_ino)
                or (current_dir.st_dev, current_dir.st_ino) != (actual_dir.st_dev, actual_dir.st_ino)):
            os.unlink(name, dir_fd=final_fd)
            raise AppError("OUTPUT_INVALID", 500)
        os.fsync(final_fd)
        return settings.files_dir / job_id / name
    except OSError as exc:
        raise AppError("OUTPUT_INVALID", 500) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


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


@dataclass
class OpenArtifact:
    """An already opened regular artifact; keep its lease for the entire response."""

    handle: BinaryIO
    lease_id: str
    artifact: dict[str, Any]
    size: int


def _open_output(settings: Settings, job_id: str, contract: dict, artifact: dict) -> BinaryIO:
    """Open each component without following links, retaining stable directories."""
    _job_component(job_id)
    extension = str(contract.get("ext") or "")
    if not re.fullmatch(r"[a-z0-9]{1,10}", extension):
        raise AppError("FILE_MISSING", 410)
    name = f"output.{extension}"
    if artifact.get("relative_path") != f"files/{job_id}/{name}":
        raise AppError("FILE_MISSING", 410)
    descriptors: list[int] = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptors.append(os.open(settings.data_dir, flags))
        for component in ("files", job_id):
            descriptors.append(os.open(component, flags, dir_fd=descriptors[-1]))
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptors[-1])
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0
                or info.st_size != artifact.get("bytes")):
            os.close(fd)
            raise AppError("FILE_MISSING", 410)
        return os.fdopen(fd, "rb")
    except OSError as exc:
        raise AppError("FILE_MISSING", 410) from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _file_error(row) -> AppError:
    if row is None:
        return AppError("NOT_FOUND", 404)
    return AppError("FILE_EXPIRED" if row["file_state"] == "expired" else "FILE_MISSING", 410)


def open_artifact(conn: sqlite3.Connection, settings: Settings, job_id: str, *, lease_seconds: int = 600) -> OpenArtifact:
    """Validate state/TTL, open a durable handle and lease under one write lock.

    Delete/expiry/pin use the same SQLite lock. An existing descriptor can finish
    after a hostile external unlink; no lazy path open occurs after success.
    """
    opened = None
    failure = None
    try:
        with transaction(conn):
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None or row["file_state"] != "available" or not row["artifact_json"]:
                failure = _file_error(row)
            elif not row["keep_on_server"] and row["file_expires_at"] and row["file_expires_at"] <= utc_iso():
                # Existing leased transfers retain bytes, but new access is denied.
                if not active_leases(conn, job_id):
                    _expire_locked(conn, settings, job_id)
                failure = AppError("FILE_EXPIRED", 410)
            else:
                artifact = json.loads(row["artifact_json"])
                try:
                    handle = _open_output(settings, job_id, json.loads(row["contract_json"]), artifact)
                except AppError as exc:
                    conn.execute("UPDATE jobs SET file_state = 'missing', revision = revision + 1, updated_at = ? WHERE id = ?", (utc_iso(), job_id))
                    failure = exc
                else:
                    lease_id = secrets.token_hex(16)
                    opened = OpenArtifact(handle, lease_id, artifact, os.fstat(handle.fileno()).st_size)
                    conn.execute("INSERT INTO transfer_leases(id, job_id, expires_at) VALUES (?, ?, ?)", (lease_id, job_id, utc_iso(utc_now() + timedelta(seconds=lease_seconds))))
    except BaseException:
        if opened is not None:
            opened.handle.close()
        raise
    if failure:
        raise failure
    assert opened is not None
    return opened


def renew_lease(conn: sqlite3.Connection, lease_id: str, *, seconds: int = 600) -> bool:
    with transaction(conn):
        result = conn.execute("UPDATE transfer_leases SET expires_at = ? WHERE id = ?", (utc_iso(utc_now() + timedelta(seconds=seconds)), lease_id))
    return result.rowcount == 1


def release_lease(conn: sqlite3.Connection, lease_id: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM transfer_leases WHERE id = ?", (lease_id,))


def _expire_locked(conn: sqlite3.Connection, settings: Settings, job_id: str) -> None:
    conn.execute("UPDATE jobs SET file_state = 'expired', artifact_json = NULL, file_expires_at = NULL, revision = revision + 1, updated_at = ? WHERE id = ? AND file_state = 'available' AND keep_on_server = 0", (utc_iso(), job_id))
    # Keep deletion inside the state transaction so a later pin cannot resurrect it.
    remove_tree(job_final_dir(settings, job_id))


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
            ORDER BY file_expires_at, id LIMIT 100
            """,
            (now,),
        ).fetchall()
        for row in rows:
            if active_leases(conn, row["id"]):
                continue
            _expire_locked(conn, settings, row["id"])
            removed += 1
    return removed


def prune_old_history(conn: sqlite3.Connection, settings: Settings) -> int:
    cutoff = utc_iso(utc_now() - timedelta(seconds=settings.history_retention_seconds))
    with transaction(conn):
        # Keep retry ancestry while any child remains. Tombstones retain request
        # identity for at least seven days after removal, without retaining media.
        candidates = conn.execute(
            """SELECT id FROM jobs j WHERE created_at < ? AND file_state != 'available'
            AND status IN ('succeeded', 'failed', 'cancelled', 'interrupted')
            AND NOT EXISTS (SELECT 1 FROM jobs child WHERE child.parent_job_id = j.id)
            AND NOT EXISTS (SELECT 1 FROM transfer_leases l WHERE l.job_id = j.id AND l.expires_at > ?)
            ORDER BY created_at LIMIT 500""",
            (cutoff, utc_iso()),
        ).fetchall()
        tombstone_until = utc_iso(utc_now() + timedelta(days=7))
        for row in candidates:
            conn.execute("UPDATE idempotency_keys SET job_id = NULL, expires_at = ? WHERE job_id = ?", (tombstone_until, row["id"]))
            conn.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
        prune_metadata(conn, settings)
        return len(candidates)


def prune_metadata(conn: sqlite3.Connection, settings: Settings) -> None:
    """Finite metadata lifetimes; referenced analyses and live work survive."""
    now = utc_iso()
    cutoff = utc_iso(utc_now() - timedelta(seconds=max(settings.history_retention_seconds, 7 * 86400)))
    with transaction(conn):
        conn.execute("DELETE FROM analyses WHERE id IN (SELECT id FROM analyses WHERE expires_at <= ? AND NOT EXISTS (SELECT 1 FROM jobs WHERE jobs.analysis_id = analyses.id) LIMIT 500)", (now,))
        conn.execute("DELETE FROM sessions WHERE id IN (SELECT id FROM sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL LIMIT 500)", (now,))
        conn.execute("DELETE FROM transfer_leases WHERE id IN (SELECT id FROM transfer_leases WHERE expires_at <= ? LIMIT 500)", (now,))
        conn.execute("DELETE FROM analysis_slots WHERE id IN (SELECT id FROM analysis_slots WHERE expires_at <= ? LIMIT 500)", (now,))
        conn.execute("DELETE FROM provider_cooldown WHERE provider IN (SELECT provider FROM provider_cooldown WHERE until_at <= ? LIMIT 500)", (now,))
        conn.execute("DELETE FROM login_attempts WHERE id IN (SELECT id FROM login_attempts WHERE at < ? LIMIT 500)", (utc_iso(utc_now() - timedelta(days=1)),))
        # Legacy keys without a row become tombstones before they can expire.
        conn.execute("UPDATE idempotency_keys SET job_id = NULL, expires_at = ? WHERE job_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM jobs WHERE jobs.id = idempotency_keys.job_id)", (utc_iso(utc_now() + timedelta(days=7)),))
        conn.execute("DELETE FROM idempotency_keys WHERE key IN (SELECT key FROM idempotency_keys WHERE job_id IS NULL AND ((expires_at IS NOT NULL AND expires_at <= ?) OR (expires_at IS NULL AND created_at < ?)) LIMIT 500)", (now, cutoff))
        conn.execute("DELETE FROM storage_reservations WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE jobs.id = storage_reservations.job_id AND jobs.status IN ('queued', 'running'))")
    # Each child diagnostic is bounded at write time; old terminal diagnostics
    # cannot accumulate forever after the history record has disappeared.
    for path in settings.log_dir.glob("*"):
        try:
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < utc_now().timestamp() - settings.history_retention_seconds:
                path.unlink()
        except OSError:
            continue


def reservation_bytes(settings: Settings, contract: dict[str, Any]) -> int:
    """Reserve the full execution budget, including unknown inputs and output.

    Estimates never weaken admission. Actual workspace bytes replace the reserved
    bytes as work grows, rather than being charged for a second time.
    """
    estimate = contract.get("size_estimate")
    if isinstance(estimate, int) and not contract.get("size_is_estimate") and estimate > settings.max_output_bytes:
        raise AppError("LIMIT_EXCEEDED", 413)
    return settings.max_workspace_bytes


def outstanding_reservations(conn: sqlite3.Connection, settings: Settings, *, exclude_job_id: str | None = None) -> int:
    rows = conn.execute("SELECT job_id, reserved_bytes FROM storage_reservations").fetchall()
    return sum(max(0, row["reserved_bytes"] - directory_size(job_workspace(settings, row["job_id"]))) for row in rows if row["job_id"] != exclude_job_id)


def _capacity(conn: sqlite3.Connection, settings: Settings, reserve: int, *, job_id: str | None = None) -> None:
    own_written = directory_size(job_workspace(settings, job_id)) if job_id else 0
    remaining = max(0, reserve - own_written)
    unspent = outstanding_reservations(conn, settings, exclude_job_id=job_id) + remaining
    # Include SQLite/WAL, logs and other managed state in the volume budget.
    used = directory_size(settings.data_dir)
    if used + unspent > settings.max_storage_bytes:
        raise AppError("STORAGE_FULL", 507, retryable=False)
    if free_bytes(settings) < settings.min_free_bytes + unspent:
        raise AppError("STORAGE_FULL", 507, retryable=False)


def reserve_job(conn: sqlite3.Connection, settings: Settings, job_id: str, contract: dict[str, Any]) -> None:
    with transaction(conn):
        reserve = reservation_bytes(settings, contract)
        _capacity(conn, settings, reserve, job_id=job_id)
        now = utc_iso()
        conn.execute("INSERT INTO storage_reservations(job_id, reserved_bytes, created_at, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET reserved_bytes = excluded.reserved_bytes, updated_at = excluded.updated_at", (job_id, reserve, now, now))


def release_reservation(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("DELETE FROM storage_reservations WHERE job_id = ?", (job_id,))


def recheck_reservation(conn: sqlite3.Connection, settings: Settings, job_id: str) -> None:
    row = conn.execute("SELECT contract_json FROM jobs WHERE id = ? AND status IN ('queued', 'running')", (job_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", 404)
    reserve_job(conn, settings, job_id, json.loads(row["contract_json"]))


def reconcile_reservations(conn: sqlite3.Connection, settings: Settings) -> None:
    """Remove terminal charges and admit legacy queued rows before execution."""
    with transaction(conn):
        conn.execute("DELETE FROM storage_reservations WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE jobs.id = storage_reservations.job_id AND jobs.status IN ('queued', 'running'))")


def ensure_space(conn: sqlite3.Connection, settings: Settings, estimated: int | None) -> None:
    """Compatibility capacity check; admission uses reserve_job transactionally."""
    with transaction(conn):
        expire_finished_files(conn, settings)
        reserve = reservation_bytes(settings, {"size_estimate": estimated})
        _capacity(conn, settings, reserve)
