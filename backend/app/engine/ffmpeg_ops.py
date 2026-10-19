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
    # MP4 language fields require ISO 639-2, not two-letter UI locales.
    base = language.lower().replace("_", "-").split("-", 1)[0]
    iso3 = {"ko": "kor", "en": "eng", "ja": "jpn", "zh": "zho", "es": "spa", "fr": "fra", "de": "deu"}.get(base, base)
    return ["-metadata:s:a:0", f"language={iso3}"]


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
                f"scale={width}:{height}:flags=lanczos,setsar=1",
                "-fps_mode",
                "passthrough",
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
        cmd.extend(["-metadata:s:v:0", "rotate=0", "-movflags", "+faststart"])
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
    """Standalone runner with a bounded stderr tail and guaranteed reap."""
    import selectors
    import os
    import time
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    selector.register(proc.stderr, selectors.EVENT_READ)
    tail = b""
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait(timeout=5)
                return 124
            for key, _ in selector.select(timeout=0.2):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                tail = (tail + data)[-4000:]
        return proc.wait(timeout=5)
    finally:
        selector.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stderr:
            proc.stderr.close()
        run_ffmpeg.last_stderr = tail.decode("utf-8", errors="replace")


run_ffmpeg.last_stderr = ""
