"""ffprobe validation of finished files."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.services.format_planner import display_size, frame_rate, is_hdr, norm_language, norm_rotation


def probe(settings: Settings, path: Path) -> dict[str, Any]:
    if not Path(settings.ffprobe_path).exists():
        raise AppError("DEPENDENCY_MISSING", 500)
    proc = subprocess.run(
        [
            settings.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise AppError("OUTPUT_INVALID", 500)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AppError("OUTPUT_INVALID", 500) from exc


def _rate(value: Any) -> float | None:
    return frame_rate(value)


def media_rotation(video: dict[str, Any]) -> int:
    for item in video.get("side_data_list") or []:
        if item.get("rotation") is not None:
            return norm_rotation(item["rotation"])
    return norm_rotation((video.get("tags") or {}).get("rotate"))


def duration_tolerance(duration: float) -> float:
    """Container/encoder delay allowance: 150 ms to 2 s, never 8% truncation."""
    return max(0.15, min(2.0, duration * 0.001))


def validate_output(settings: Settings, path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise AppError("OUTPUT_INVALID", 500)
    if path.stat().st_size > settings.max_output_bytes:
        raise AppError("LIMIT_EXCEEDED", 500)
    info = probe(settings, path)
    fmt = info.get("format") or {}
    format_name = str(fmt.get("format_name") or "")
    container = contract.get("container")
    expected = {
        "mp4": "mp4",
        "m4a": "mp4",
        "mp3": "mp3",
        "webm": "webm",
        "ogg": "ogg",
    }.get(container or "", "")
    if expected and expected not in format_name.split(","):
        raise AppError("OUTPUT_INVALID", 500)
    streams = info.get("streams") or []
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if contract.get("has_video"):
        if len(videos) != 1:
            raise AppError("OUTPUT_INVALID", 500)
        video = videos[0]
        if video.get("codec_name") != contract.get("output_vcodec"):
            raise AppError("OUTPUT_INVALID", 500)
        if contract.get("output_vcodec") == "h264":
            if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
                raise AppError("OUTPUT_INVALID", 500)
            depth = video.get("bits_per_raw_sample")
            if depth not in (None, "8", 8):
                raise AppError("OUTPUT_INVALID", 500)
        if is_hdr(video):
            raise AppError("OUTPUT_INVALID", 500)
        encoded_width = int(video.get("width") or 0)
        encoded_height = int(video.get("height") or 0)
        rotation = media_rotation(video)
        if rotation < 0 or rotation != norm_rotation(contract.get("output_rotation")):
            raise AppError("OUTPUT_INVALID", 500)
        for field, actual in (("output_encoded_width", encoded_width), ("output_encoded_height", encoded_height)):
            if contract.get(field) and actual != int(contract[field]):
                raise AppError("OUTPUT_INVALID", 500)
        width, height = display_size(encoded_width, encoded_height, rotation)
        promised_rate = _rate(contract.get("output_fps"))
        actual_rate = _rate(video.get("avg_frame_rate"))
        if promised_rate and (actual_rate is None or abs(actual_rate - promised_rate) > max(0.01, min(0.2, promised_rate * 0.005))):
            raise AppError("OUTPUT_INVALID", 500)
        if contract.get("output_width") and abs(width - int(contract["output_width"])) > 2:
            raise AppError("OUTPUT_INVALID", 500)
        if contract.get("output_height") and abs(height - int(contract["output_height"])) > 2:
            raise AppError("OUTPUT_INVALID", 500)
    elif videos and contract.get("kind") != "mp4":
        raise AppError("OUTPUT_INVALID", 500)
    if contract.get("has_audio"):
        if len(audios) != 1:
            raise AppError("OUTPUT_INVALID", 500)
        audio = audios[0]
        expected_audio = contract.get("output_acodec")
        actual = audio.get("codec_name")
        if expected_audio == "aac" and actual not in {"aac"}:
            raise AppError("OUTPUT_INVALID", 500)
        if expected_audio == "mp3" and actual not in {"mp3"}:
            raise AppError("OUTPUT_INVALID", 500)
        if expected_audio == "opus" and actual not in {"opus"}:
            raise AppError("OUTPUT_INVALID", 500)
        if expected_audio == "vorbis" and actual not in {"vorbis"}:
            raise AppError("OUTPUT_INVALID", 500)
        if contract.get("kind") == "mp3" and contract.get("mp3_bitrate"):
            bit_rate = audio.get("bit_rate") or fmt.get("bit_rate")
            if bit_rate:
                kbps = int(bit_rate) / 1000
                target = int(contract["mp3_bitrate"])
                if abs(kbps - target) > max(24, target * 0.2):
                    raise AppError("OUTPUT_INVALID", 500)
        language = contract.get("audio_language")
        tags = audio.get("tags") or {}
        reported = (tags.get("language") or tags.get("LANGUAGE") or "").lower()
        if language and reported and (norm_language(reported) or "").split("-")[0] != (norm_language(language) or "").split("-")[0]:
            raise AppError("OUTPUT_INVALID", 500)
    elif audios:
        raise AppError("OUTPUT_INVALID", 500)
    duration = fmt.get("duration")
    try:
        actual_duration = float(duration)
    except (ValueError, TypeError) as exc:
        raise AppError("OUTPUT_INVALID", 500) from exc
    if actual_duration <= 0 or not math.isfinite(actual_duration):
        raise AppError("OUTPUT_INVALID", 500)
    expected_duration = contract.get("duration")
    if expected_duration and abs(actual_duration - float(expected_duration)) > duration_tolerance(float(expected_duration)):
        raise AppError("OUTPUT_INVALID", 500)
    return {
        "bytes": path.stat().st_size,
        "duration": actual_duration,
        "format_name": format_name,
        "video": {
            "codec": videos[0].get("codec_name"),
            "encoded_width": int(videos[0].get("width") or 0),
            "encoded_height": int(videos[0].get("height") or 0),
            "rotation": media_rotation(videos[0]),
            "fps": _rate(videos[0].get("avg_frame_rate")),
        } if videos else None,
        "audio": {
            "codec": audios[0].get("codec_name"),
            "bitrate_kbps": int(audios[0]["bit_rate"]) / 1000 if audios[0].get("bit_rate") else None,
        } if audios else None,
    }
