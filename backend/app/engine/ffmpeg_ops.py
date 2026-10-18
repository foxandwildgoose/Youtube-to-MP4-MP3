"""Argument-array ffmpeg operations. Never uses a shell."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.config import Settings


def _even_box(width: int, height: int, cap: int) -> tuple[int, int]:
    long_cap = {1080: 1920, 2160: 3840}.get(cap, int(round(cap * 16 / 9)))
    scale = min(1.0, cap / max(1, min(width, height)), long_cap / max(1, max(width, height)))
    tw = max(2, int(width * scale) // 2 * 2)
    th = max(2, int(height * scale) // 2 * 2)
    return tw, th


def language_args(language: str | None) -> list[str]:
    if not language:
        return []
    return ["-metadata:s:a:0", f"language={language}"]


def build_command(
    settings: Settings,
    contract: dict[str, Any],
    inputs: list[Path],
    output: Path,
    progress_path: Path,
) -> list[str]:
    ffmpeg = settings.ffmpeg_path
    cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner"]
    for path in inputs:
        cmd.extend(["-i", str(path)])
    kind = contract["kind"]
    if kind == "mp4" and not contract.get("conversion"):
        if len(inputs) == 1:
            cmd.extend(["-map", "0:v:0"])
            if contract.get("has_audio"):
                cmd.extend(["-map", "0:a:0"])
        else:
            cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])
        cmd.extend(["-c", "copy", "-movflags", "+faststart"])
    elif kind == "mp4" and contract.get("conversion"):
        width = int(contract["output_width"])
        height = int(contract["output_height"])
        cmd.extend(["-map", "0:v:0"])
        if contract.get("has_audio"):
            audio_index = "1:a:0" if len(inputs) > 1 else "0:a:0"
            cmd.extend(["-map", audio_index])
        cmd.extend(
            [
                "-vf",
                f"scale={width}:{height}:flags=lanczos",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-profile:v",
                "high",
                "-preset",
                "veryfast",
                "-crf",
                "20",
            ]
        )
        if contract.get("has_audio"):
            cmd.extend(["-c:a", "aac", "-b:a", "160k"])
        cmd.extend(["-movflags", "+faststart"])
    elif kind == "mp3":
        rate = int(contract.get("mp3_bitrate") or 192)
        cmd.extend(["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", f"{rate}k"])
    elif kind == "original_audio":
        cmd.extend(["-map", "0:a:0", "-vn", "-c:a", "copy"])
    else:
        raise RuntimeError("unsupported contract")
    cmd.extend(language_args(contract.get("audio_language")))
    cmd.extend(["-progress", str(progress_path), str(output)])
    return cmd


def run_ffmpeg(cmd: list[str], timeout: int) -> int:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return 124
    # Keep a bounded diagnostic on the process object via return only.
    if stderr:
        tail = stderr[-4000:]
        run_ffmpeg.last_stderr = tail.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    return proc.returncode


run_ffmpeg.last_stderr = ""  # type: ignore[attr-defined]
