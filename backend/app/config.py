"""Operator configuration. Defaults match the product specification."""

from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    # A misspelled authentication flag must not silently turn protection off.
    raise SystemExit(f"Unsupported configuration: {name} must be a boolean (0/1, false/true, no/yes, off/on)")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"Unsupported configuration: {name} must be an integer") from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return default if raw is None or raw == "" else float(raw)
    except ValueError as exc:
        raise SystemExit(f"Unsupported configuration: {name} must be numeric") from exc


def _path_env(name: str, fallback: str) -> str:
    raw = os.environ.get(name)
    if raw:
        return shutil.which(raw) or raw
    found = shutil.which(Path(fallback).name)
    if found:
        return found
    return fallback


GIB = 1024**3


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    media_adapter: str
    allow_fixture_urls: bool
    fixture_catalog: Path | None
    local_http: bool
    require_password: bool
    allow_http_bootstrap: bool
    allowed_hosts: tuple[str, ...]
    enable_playlists: bool
    enable_transcoding: bool
    allow_test_hooks: bool
    media_concurrency: int
    analysis_concurrency: int
    max_waiting_jobs: int
    analysis_ttl_seconds: int
    analysis_deadline_seconds: int
    max_source_duration_seconds: int
    native_mp4_cap: int
    default_mp4_cap: int
    conversion_cap: int
    mp3_default_kbps: int
    max_input_bytes: int
    max_output_bytes: int
    max_workspace_bytes: int
    max_storage_bytes: int
    min_free_bytes: int
    active_job_deadline_seconds: int
    file_ttl_seconds: int
    history_retention_seconds: int
    max_auto_retries: int
    session_ttl_seconds: int
    sse_heartbeat_seconds: float
    cookie_name: str
    ffmpeg_path: str
    ffprobe_path: str
    deno_path: str
    log_max_bytes: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "state" / "app.db"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def demo_data(self) -> bool:
        return self.media_adapter == "fixture"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "/workspace/data")).resolve()
    catalog = os.environ.get("FIXTURE_CATALOG")
    hosts = tuple(
        h.strip().lower()
        for h in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
        if h.strip()
    )
    return Settings(
        data_dir=data_dir,
        media_adapter=os.environ.get("MEDIA_ADAPTER", "ytdlp").strip().lower(),
        allow_fixture_urls=_bool("ALLOW_FIXTURE_URLS", False),
        fixture_catalog=Path(catalog).resolve() if catalog else None,
        local_http=_bool("LOCAL_HTTP", True),
        require_password=_bool("REQUIRE_PASSWORD", True),
        allow_http_bootstrap=_bool("ALLOW_HTTP_BOOTSTRAP", False),
        allowed_hosts=hosts,
        enable_playlists=_bool("ENABLE_PLAYLISTS", False),
        enable_transcoding=_bool("ENABLE_TRANSCODING", False),
        allow_test_hooks=_bool("ALLOW_TEST_HOOKS", False),
        media_concurrency=_int("MEDIA_CONCURRENCY", 1),
        analysis_concurrency=_int("ANALYSIS_CONCURRENCY", 1),
        max_waiting_jobs=_int("MAX_WAITING_JOBS", 20),
        analysis_ttl_seconds=_int("ANALYSIS_TTL_SECONDS", 600),
        analysis_deadline_seconds=_int("ANALYSIS_DEADLINE_SECONDS", 60),
        max_source_duration_seconds=_int("MAX_SOURCE_DURATION_SECONDS", 4 * 3600),
        native_mp4_cap=_int("NATIVE_MP4_CAP", 2160),
        default_mp4_cap=_int("DEFAULT_MP4_CAP", 1080),
        conversion_cap=_int("CONVERSION_CAP", 1080),
        mp3_default_kbps=_int("MP3_DEFAULT_KBPS", 192),
        max_input_bytes=_int("MAX_INPUT_BYTES", 5 * GIB),
        max_output_bytes=_int("MAX_OUTPUT_BYTES", 5 * GIB),
        max_workspace_bytes=_int("MAX_WORKSPACE_BYTES", 12 * GIB),
        max_storage_bytes=_int("MAX_STORAGE_BYTES", 50 * GIB),
        min_free_bytes=_int("MIN_FREE_BYTES", 2 * GIB),
        active_job_deadline_seconds=_int("ACTIVE_JOB_DEADLINE_SECONDS", 2 * 3600),
        file_ttl_seconds=_int("FILE_TTL_SECONDS", 24 * 3600),
        history_retention_seconds=_int("HISTORY_RETENTION_SECONDS", 90 * 24 * 3600),
        max_auto_retries=_int("MAX_AUTO_RETRIES", 2),
        session_ttl_seconds=_int("SESSION_TTL_SECONDS", 12 * 3600),
        sse_heartbeat_seconds=_float("SSE_HEARTBEAT_SECONDS", 5),
        cookie_name=os.environ.get("SESSION_COOKIE", "seorap_session"),
        ffmpeg_path=_path_env("FFMPEG_PATH", "/usr/local/bin/ffmpeg"),
        ffprobe_path=_path_env("FFPROBE_PATH", "/workspace/bin/ffprobe"),
        deno_path=_path_env("DENO_PATH", "/workspace/bin/deno"),
        log_max_bytes=_int("LOG_MAX_BYTES", 5 * 1024 * 1024),
    )


def validate_limits(settings: Settings) -> None:
    problems: list[str] = []
    if settings.media_adapter not in {"ytdlp", "fixture"}:
        problems.append("MEDIA_ADAPTER must be ytdlp or fixture")
    if settings.media_adapter == "fixture" and not settings.allow_fixture_urls:
        problems.append("fixture adapter requires ALLOW_FIXTURE_URLS=1")
    if settings.media_concurrency != 1:
        problems.append("MEDIA_CONCURRENCY must be 1 (the worker supports one media task)")
    positive_fields = (
        "analysis_concurrency", "max_waiting_jobs", "analysis_ttl_seconds", "analysis_deadline_seconds",
        "max_source_duration_seconds", "native_mp4_cap", "default_mp4_cap", "conversion_cap",
        "max_input_bytes", "max_output_bytes", "max_workspace_bytes", "max_storage_bytes",
        "active_job_deadline_seconds", "file_ttl_seconds", "history_retention_seconds",
        "session_ttl_seconds", "log_max_bytes",
    )
    for name in positive_fields:
        if getattr(settings, name) < 1:
            problems.append(f"{name.upper()} must be >= 1")
    if not math.isfinite(settings.sse_heartbeat_seconds) or settings.sse_heartbeat_seconds <= 0:
        problems.append("SSE_HEARTBEAT_SECONDS must be finite and > 0")
    if settings.default_mp4_cap > settings.native_mp4_cap:
        problems.append("DEFAULT_MP4_CAP cannot exceed NATIVE_MP4_CAP")
    if settings.conversion_cap > settings.native_mp4_cap:
        problems.append("CONVERSION_CAP cannot exceed NATIVE_MP4_CAP")
    if settings.mp3_default_kbps not in {128, 192, 320}:
        problems.append("MP3_DEFAULT_KBPS must be 128, 192, or 320")
    if settings.max_input_bytes > settings.max_workspace_bytes:
        problems.append("MAX_INPUT_BYTES cannot exceed MAX_WORKSPACE_BYTES")
    if settings.max_output_bytes > settings.max_workspace_bytes:
        problems.append("MAX_OUTPUT_BYTES cannot exceed MAX_WORKSPACE_BYTES")
    if settings.min_free_bytes < 0 or settings.max_storage_bytes < 1:
        problems.append("storage limits are inconsistent")
    if settings.analysis_ttl_seconds < 1 or settings.analysis_deadline_seconds < 1:
        problems.append("analysis timing is inconsistent")
    if settings.file_ttl_seconds < 1 or settings.active_job_deadline_seconds < 1:
        problems.append("job timing is inconsistent")
    if not 0 <= settings.max_auto_retries <= 10:
        problems.append("MAX_AUTO_RETRIES must be between 0 and 10")
    if not settings.allowed_hosts:
        problems.append("ALLOWED_HOSTS cannot be empty")
    if problems:
        raise SystemExit("Unsupported configuration: " + "; ".join(problems))
