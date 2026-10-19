"""Bounded single-video analysis and optional playlist inspection."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.db import connect, transaction, utc_iso, utc_now
from app.engine_runner import execute
from app.errors import AppError
from app.services.format_planner import plan_outputs
from app.services.slots import acquire_slot, release_slot
from app.services.url_policy import require_playlist, require_video


def _cooldown_seconds(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT until_at FROM provider_cooldown WHERE provider = 'youtube'").fetchone()
    if not row:
        return None
    from datetime import datetime

    until = datetime.fromisoformat(row["until_at"])
    delta = (until - utc_now()).total_seconds()
    if delta <= 0:
        return None
    return int(delta) + 1


def assert_no_cooldown(conn: sqlite3.Connection) -> None:
    remaining = _cooldown_seconds(conn)
    if remaining:
        raise AppError("SOURCE_RATE_LIMITED", 429, retryable=True, retry_after=remaining)


def set_cooldown(conn: sqlite3.Connection, seconds: int, reason: str) -> None:
    until = utc_iso(utc_now() + timedelta(seconds=max(1, seconds)))
    conn.execute(
        """
        INSERT INTO provider_cooldown (provider, until_at, reason) VALUES ('youtube', ?, ?)
        ON CONFLICT(provider) DO UPDATE SET until_at = MAX(provider_cooldown.until_at, excluded.until_at), reason = excluded.reason
        """,
        (until, reason[:200]),
    )


def analyze_video(settings: Settings, url: str) -> dict[str, Any]:
    target = require_video(url)
    conn = connect(settings)
    try:
        assert_no_cooldown(conn)
    finally:
        conn.close()
    payload = _payload(settings, "probe", target.canonical_url, target.video_id)
    slot_id = _acquire_wait(settings)
    try:
        outcome = execute(payload, settings, deadline_seconds=settings.analysis_deadline_seconds)
    finally:
        release_slot(settings, slot_id)
    info = _outcome_info(settings, outcome)
    _reject_source(settings, info)
    # Saved operator preference governs future analyses, never queued contracts.
    conn = connect(settings)
    try:
        preference = conn.execute("SELECT mp3_bitrate FROM preferences WHERE id = 1").fetchone()
        effective_rate = int(preference["mp3_bitrate"]) if preference else settings.mp3_default_kbps
    finally:
        conn.close()
    planned = plan_outputs(info.get("streams") or [], info.get("duration"), settings, mp3_default_kbps=effective_rate)
    analysis_id = secrets.token_hex(16)
    choices = []
    for choice in planned["choices"]:
        choice_id = secrets.token_urlsafe(12)
        choices.append({"choice_id": choice_id, "contract": choice, "public": public_choice(choice_id, choice)})
    now = utc_now()
    metadata = {
        "video_id": info.get("video_id") or target.video_id,
        "canonical_url": target.canonical_url,
        "title": info.get("title") or "",
        "channel": info.get("channel") or "",
        "duration_seconds": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "ignored_timestamp": target.ignored_timestamp,
        "ignored_playlist": target.ignored_playlist,
        "live_status": info.get("live_status"),
        "effective_mp3_bitrate": planned["effective_mp3_bitrate"],
    }
    conn = connect(settings)
    try:
        with transaction(conn):
            conn.execute(
                """
                INSERT INTO analyses (id, canonical_url, video_id, metadata_json, choices_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    target.canonical_url,
                    target.video_id,
                    json.dumps(metadata),
                    json.dumps(choices),
                    utc_iso(now),
                    utc_iso(now + timedelta(seconds=settings.analysis_ttl_seconds)),
                ),
            )
    finally:
        conn.close()
    return public_analysis(analysis_id, metadata, planned["audio_tracks"], choices, utc_iso(now + timedelta(seconds=settings.analysis_ttl_seconds)))


def analyze_playlist(settings: Settings, url: str) -> dict[str, Any]:
    if not settings.enable_playlists:
        raise AppError("PLAYLISTS_DISABLED", 403)
    target = require_playlist(url)
    conn = connect(settings)
    try:
        assert_no_cooldown(conn)
    finally:
        conn.close()
    payload = _payload(settings, "playlist", target.canonical_url, None)
    payload["playlist_id"] = target.playlist_id
    payload["playlist_limit"] = 20
    slot_id = _acquire_wait(settings)
    try:
        outcome = execute(payload, settings, deadline_seconds=settings.analysis_deadline_seconds)
    finally:
        release_slot(settings, slot_id)
    if outcome["status"] != "ok":
        _raise_outcome(settings, outcome)
    playlist = outcome["result"].get("playlist") or {}
    entries = list(playlist.get("entries") or [])[:20]
    return {
        "playlist_id": target.playlist_id,
        "canonical_url": target.canonical_url,
        "limit": 20,
        "limited": True,
        "stopped_at_cap": bool(playlist.get("stopped") or len(entries) >= 20),
        "entries": entries,
    }


def load_analysis(conn: sqlite3.Connection, analysis_id: str, *, require_fresh: bool) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", 404)
    if require_fresh and row["expires_at"] <= utc_iso():
        raise AppError("ANALYSIS_EXPIRED", 409)
    return {
        "id": row["id"],
        "canonical_url": row["canonical_url"],
        "video_id": row["video_id"],
        "metadata": json.loads(row["metadata_json"]),
        "choices": json.loads(row["choices_json"]),
        "expires_at": row["expires_at"],
    }


def public_choice(choice_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "choice_id": choice_id,
        "kind": contract["kind"],
        "label": contract["label"],
        "conversion_required": bool(contract.get("conversion")),
        "requires_consent": bool(contract.get("requires_consent")),
        "width": contract.get("output_width"),
        "height": contract.get("output_height"),
        "fps": contract.get("output_fps"),
        "vcodec": contract.get("output_vcodec"),
        "acodec": contract.get("output_acodec"),
        "audio_language": contract.get("audio_language"),
        "audio_role": contract.get("audio_role"),
        "container": contract.get("container"),
        "estimated_bytes": contract.get("size_estimate"),
        "size_is_estimate": contract.get("size_is_estimate"),
        "resolution_label": contract.get("resolution_label"),
        "portrait": contract.get("portrait"),
        "bitrate_kbps": contract.get("mp3_bitrate"),
        "is_default": bool(contract.get("is_default")),
        "track_key": contract.get("audio_track_key"),
        "encoded_width": contract.get("output_encoded_width"),
        "encoded_height": contract.get("output_encoded_height"),
        "rotation": contract.get("output_rotation", 0),
        "input_bytes": contract.get("input_bytes"),
        "input_size_provenance": contract.get("input_size_provenance", "unknown"),
        "estimated_output_bytes": contract.get("estimated_output_bytes"),
        "output_size_provenance": contract.get("output_size_provenance", "unknown"),
        "expected_workspace_bytes": contract.get("expected_workspace_bytes"),
    }


def public_analysis(analysis_id: str, metadata: dict[str, Any], tracks: list[dict[str, Any]], choices: list[dict[str, Any]], expires_at: str) -> dict[str, Any]:
    return {
        "analysis_id": analysis_id,
        "expires_at": expires_at,
        "source": {
            "video_id": metadata["video_id"],
            "canonical_url": metadata["canonical_url"],
            "title": metadata["title"],
            "channel": metadata["channel"],
            "duration_seconds": metadata["duration_seconds"],
            "thumbnail_url": f"/api/v1/analyses/{analysis_id}/thumbnail" if metadata.get("thumbnail") else None,
            "live_status": metadata.get("live_status"),
            "ignored_timestamp": bool(metadata.get("ignored_timestamp")),
            "ignored_playlist": bool(metadata.get("ignored_playlist")),
        },
        "effective_mp3_bitrate": metadata.get("effective_mp3_bitrate"),
        "audio_tracks": [
            {key: track.get(key) for key in ("track_key", "language", "role", "codec", "codecs", "representation_count")}
            for track in tracks
        ],
        "choices": [item["public"] for item in choices],
    }


def _payload(settings: Settings, action: str, url: str, video_id: str | None) -> dict[str, Any]:
    return {
        "action": action,
        "url": url,
        "video_id": video_id,
        "adapter": settings.media_adapter,
        "catalog": str(settings.fixture_catalog) if settings.fixture_catalog else None,
        "allow_test_hooks": settings.allow_test_hooks,
        "ffmpeg": settings.ffmpeg_path,
        "ffprobe": settings.ffprobe_path,
        "deno": settings.deno_path,
        "manage_slot": False,
        "native_cap": settings.native_mp4_cap,
    }


def _acquire_wait(settings: Settings) -> str:
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        slot_id = acquire_slot(settings, "api-probe")
        if slot_id:
            return slot_id
        time.sleep(0.2)
    raise AppError("LIMIT_EXCEEDED", 429, retryable=True, retry_after=2)


def _outcome_info(settings: Settings, outcome: dict[str, Any]) -> dict[str, Any]:
    if outcome["status"] == "timeout":
        raise AppError("JOB_TIMEOUT", 504, retryable=True)
    if outcome["status"] != "ok":
        _raise_outcome(settings, outcome)
    return outcome["result"].get("info") or {}


def _raise_outcome(settings: Settings, outcome: dict[str, Any]) -> None:
    error = outcome.get("error") or {}
    code = error.get("code") or "ENGINE_ERROR"
    if code == "HTTP_403":
        code = "SOURCE_FORBIDDEN"
    if code == "SOURCE_RATE_LIMITED":
        conn = connect(settings)
        try:
            set_cooldown(conn, int(error.get("retry_after") or 120), "provider")
        finally:
            conn.close()
        raise AppError("SOURCE_RATE_LIMITED", 429, retryable=True, retry_after=int(error.get("retry_after") or 120))
    status = {
        "SOURCE_UNAVAILABLE": 404,
        "SOURCE_AUTH_REQUIRED": 403,
        "SOURCE_FORBIDDEN": 403,
        "FORMAT_UNAVAILABLE": 409,
        "FORMAT_CHANGED": 409,
        "DEPENDENCY_MISSING": 500,
        "LIMIT_EXCEEDED": 413,
        "JOB_TIMEOUT": 504,
    }.get(code, 502)
    raise AppError(code, status, retryable=bool(error.get("retryable")))


def _reject_source(settings: Settings, info: dict[str, Any]) -> None:
    live = info.get("live_status")
    if live in {"is_live", "is_upcoming", "post_live"}:
        raise AppError("SOURCE_UNAVAILABLE", 422)
    if live == "was_live" and not info.get("duration"):
        raise AppError("SOURCE_UNAVAILABLE", 422)
    if info.get("drm"):
        raise AppError("SOURCE_FORBIDDEN", 403)
    availability = info.get("availability")
    if availability in {"private", "needs_auth"}:
        raise AppError("SOURCE_AUTH_REQUIRED", 403)
    if availability in {"subscriber_only", "premium_only"}:
        raise AppError("SOURCE_FORBIDDEN", 403)
    duration = info.get("duration")
    if duration and float(duration) > settings.max_source_duration_seconds:
        raise AppError("LIMIT_EXCEEDED", 413)
