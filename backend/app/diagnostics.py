"""Authenticated readiness. Liveness stays on /healthz and does not touch YouTube."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.db import utc_iso, utc_now
from app.services.storage import free_bytes, managed_bytes

VERSIONS = {
    "app": "1.0.0",
    "yt_dlp": "2026.08.19",
    "yt_dlp_ejs": "0.8.0",
    "deno": "2.9.7",
    "ffmpeg": "7.0.2-static",
    "verified_on": "2026-10-18",
}


def _first_line(cmd: list[str]) -> str | None:
    if not cmd or not cmd[0] or not Path(cmd[0]).exists():
        return None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    line = (proc.stdout or proc.stderr or "").strip().splitlines()
    return line[0] if line else None


def _encoders(ffmpeg: str) -> dict[str, bool]:
    found = {"libx264": False, "aac": False, "libmp3lame": False}
    if not Path(ffmpeg).exists():
        return found
    try:
        proc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return found
    text = proc.stdout
    for name in found:
        found[name] = name in text
    return found


def diagnostics(settings: Settings, conn: sqlite3.Connection) -> dict:
    db_ok = False
    try:
        conn.execute("SELECT 1").fetchone()
        db_ok = True
    except sqlite3.Error:
        db_ok = False
    writable = os_access(settings.data_dir) and os_access(settings.tmp_dir) and os_access(settings.files_dir)
    beat = conn.execute("SELECT worker_id, beat_at, pid FROM worker_heartbeat WHERE id = 1").fetchone()
    heartbeat = None
    stale = True
    if beat and beat["beat_at"]:
        when = datetime.fromisoformat(beat["beat_at"])
        age = (utc_now() - when).total_seconds()
        stale = age > 30
        heartbeat = {"age_seconds": int(age), "stale": stale, "pid": beat["pid"]}
    encoders = _encoders(settings.ffmpeg_path)
    try:
        import yt_dlp
        import yt_dlp_ejs

        ytdlp_version = yt_dlp.version.__version__
        ejs_version = str(yt_dlp_ejs.version)
    except Exception:
        ytdlp_version = None
        ejs_version = None
    deno = _first_line([settings.deno_path, "--version"])
    ffmpeg = _first_line([settings.ffmpeg_path, "-version"])
    ffprobe = _first_line([settings.ffprobe_path, "-version"])
    ready = all(
        [
            db_ok,
            writable,
            not stale,
            bool(ytdlp_version),
            bool(ejs_version),
            bool(deno),
            bool(ffmpeg),
            bool(ffprobe),
            encoders["libx264"],
            encoders["aac"],
            encoders["libmp3lame"],
            free_bytes(settings) >= settings.min_free_bytes,
        ]
    )
    return {
        "ready": ready,
        "youtube_reachable": None,
        "demo_data": settings.demo_data,
        "database": db_ok,
        "storage_writable": writable,
        "free_bytes": free_bytes(settings),
        "managed_bytes": managed_bytes(settings),
        "minimum_free_bytes": settings.min_free_bytes,
        "storage_limit_bytes": settings.max_storage_bytes,
        "worker": heartbeat,
        "tools": {
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "deno": deno,
            "yt_dlp": ytdlp_version,
            "yt_dlp_ejs": ejs_version,
            "encoders": encoders,
        },
        "flags": {
            "playlists_enabled": settings.enable_playlists,
            "transcoding_enabled": settings.enable_transcoding,
            "local_http": settings.local_http,
            "media_adapter": settings.media_adapter,
        },
        "limits": {
            "media_concurrency": settings.media_concurrency,
            "analysis_concurrency": settings.analysis_concurrency,
            "max_waiting_jobs": settings.max_waiting_jobs,
            "analysis_ttl_seconds": settings.analysis_ttl_seconds,
            "max_source_duration_seconds": settings.max_source_duration_seconds,
            "native_mp4_cap": settings.native_mp4_cap,
            "default_mp4_cap": settings.default_mp4_cap,
            "conversion_cap": settings.conversion_cap,
            "mp3_default_kbps": settings.mp3_default_kbps,
            "file_ttl_seconds": settings.file_ttl_seconds,
            "active_job_deadline_seconds": settings.active_job_deadline_seconds,
            "max_auto_retries": settings.max_auto_retries,
        },
        "versions": {**VERSIONS, "yt_dlp_runtime": ytdlp_version, "ejs_runtime": ejs_version, "reported_at": utc_iso()},
    }


def os_access(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def disk_summary(settings: Settings) -> dict:
    usage = shutil.disk_usage(settings.data_dir)
    return {"total": usage.total, "free": usage.free, "checked_at": datetime.now(timezone.utc).isoformat()}
