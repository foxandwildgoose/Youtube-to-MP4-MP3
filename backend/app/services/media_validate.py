"""ffprobe validation of finished files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import AppError


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


def _rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        if float(den) == 0:
            return None
        return float(num) / float(den)
    return float(value)


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
        if not videos:
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
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        if contract.get("output_width") and abs(width - int(contract["output_width"])) > 2:
            raise AppError("OUTPUT_INVALID", 500)
        if contract.get("output_height") and abs(height - int(contract["output_height"])) > 2:
            raise AppError("OUTPUT_INVALID", 500)
    elif videos and contract.get("kind") != "mp4":
        raise AppError("OUTPUT_INVALID", 500)
    if contract.get("has_audio"):
        if not audios:
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
        if language and reported and reported not in {language.lower(), _iso3(language)}:
            raise AppError("OUTPUT_INVALID", 500)
    elif audios and contract.get("kind") == "mp4" and not contract.get("has_audio"):
        pass
    duration = fmt.get("duration")
    expected_duration = contract.get("duration")
    if expected_duration and duration not in (None, "N/A"):
        actual = float(duration)
        limit = max(0.75, float(expected_duration) * 0.08)
        if abs(actual - float(expected_duration)) > limit:
            raise AppError("OUTPUT_INVALID", 500)
    elif expected_duration and not duration:
        raise AppError("OUTPUT_INVALID", 500)
    return {
        "bytes": path.stat().st_size,
        "duration": float(duration) if duration not in (None, "N/A") else None,
        "format_name": format_name,
    }


def _iso3(language: str) -> str:
    return {"ko": "kor", "en": "eng", "ja": "jpn", "zh": "zho", "es": "spa", "fr": "fra", "de": "deu"}.get(
        language.lower(), language.lower()
    )
