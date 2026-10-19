"""Owned engine subprocess.

Reads one JSON payload on stdin and writes NDJSON events on stdout.
It never accepts raw yt-dlp flags, templates, or paths from the end user.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from app.services.format_planner import norm_acodec, norm_vcodec
from app.errors import AppError


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str, *, retryable: bool = False, retry_after: int | None = None) -> None:
    emit({"type": "error", "code": code, "message": message, "retryable": retryable, "retry_after": retry_after})
    raise SystemExit(2)


def classify_message(text: str) -> tuple[str, bool]:
    lowered = text.lower()
    if "429" in text or "too many request" in lowered or "rate limit" in lowered:
        return "SOURCE_RATE_LIMITED", False
    if any(phrase in lowered for phrase in ("sign in", "login required", "private video", "members only", "join this channel")):
        return "SOURCE_AUTH_REQUIRED", False
    if "drm" in lowered:
        return "SOURCE_FORBIDDEN", False
    if "403" in text or "forbidden" in lowered:
        return "HTTP_403", True
    if any(phrase in lowered for phrase in ("video unavailable", "has been removed", "account associated", "not available")):
        return "SOURCE_UNAVAILABLE", False
    if any(phrase in lowered for phrase in ("timed out", "timeout", "temporarily", "connection reset", "network")):
        return "ENGINE_ERROR", True
    return "ENGINE_ERROR", False


def _retry_after(error: Exception) -> int | None:
    """Use provider Retry-After metadata only, never an unrelated numeric token."""
    import re
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    pending, seen = [error], set()
    for _ in range(8):
        if not pending:
            break
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        response = getattr(current, "response", None)
        headers = getattr(current, "headers", None) or getattr(response, "headers", None)
        value = headers.get("Retry-After") if headers is not None else None
        if value:
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                try:
                    return max(1, int((parsedate_to_datetime(str(value)) - datetime.now(timezone.utc)).total_seconds()) + 1)
                except (TypeError, ValueError, OverflowError):
                    pass
        pending.extend([getattr(current, "__cause__", None), getattr(current, "__context__", None)])
        exc_info = getattr(current, "exc_info", None)
        if exc_info and len(exc_info) > 1:
            pending.append(exc_info[1])
    match = re.search(r"retry[- ]after\s*[:=]?\s*(\d+)\b", str(error), flags=re.I)
    return max(1, int(match.group(1))) if match else None


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        fail("ENGINE_ERROR", "Engine payload was not readable.")
    os.environ["YTDLP_NO_PLUGINS"] = "1"
    action = payload.get("action")
    try:
        if action == "probe":
            info = probe(payload)
            emit({"type": "result", "ok": True, "info": info})
        elif action == "playlist":
            listing = playlist(payload)
            emit({"type": "result", "ok": True, "playlist": listing})
        elif action == "job":
            checked = run_job(payload)
            emit({"type": "result", "ok": True, "output": payload["output_path"], "checked": checked})
        else:
            fail("ENGINE_ERROR", "Unknown engine action.")
    except SystemExit:
        raise
    except AppError as exc:
        emit({"type": "error", "code": exc.code, "message": "The operation could not continue.",
              "retryable": exc.retryable, "retry_after": exc.retry_after})
        raise SystemExit(2)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary of the subprocess
        code, retryable = classify_message(str(exc))
        fail(code, "The media engine failed.", retryable=retryable, retry_after=_retry_after(exc) if code == "SOURCE_RATE_LIMITED" else None)


def probe(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("adapter") == "fixture":
        return fixture_probe(payload)
    return ytdlp_probe(payload, download=False)


def playlist(payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("playlist_limit") or 20)
    if payload.get("adapter") == "fixture":
        return fixture_playlist(payload, limit)
    return ytdlp_playlist(payload, limit)


def run_job(payload: dict[str, Any]) -> dict[str, Any] | None:
    work = Path(payload["work_dir"])
    work.mkdir(parents=True, exist_ok=True)

    def load_info() -> dict[str, Any]:
        info = _fixture_info(payload) if payload.get("adapter") == "fixture" else ytdlp_probe(payload, download=False)
        _reject_ineligible(info, payload)
        return info

    info = _with_slot(payload, load_info)
    from app.services.match import resolve_contract

    resolved = resolve_contract(info["streams"], payload["contract"], int(payload.get("native_cap") or 2160))
    if not resolved:
        fail("FORMAT_CHANGED", "The selected format is no longer available.")
    if payload.get("adapter") == "fixture":
        sources = [fixture_materialize(payload, work)]
    else:
        sources = ytdlp_download(payload, work, resolved)
    return _ffmpeg_finish(payload, sources, resolved)


def _with_slot(payload: dict[str, Any], fn):
    if not payload.get("manage_slot"):
        return fn()
    import signal
    from app.config import load_settings
    from app.services.analysis import assert_no_cooldown
    from app.db import connect
    from app.services.slots import acquire_slot, release_slot

    from dataclasses import replace
    settings = load_settings()
    if payload.get("analysis_deadline_seconds"):
        settings = replace(settings, analysis_deadline_seconds=int(payload["analysis_deadline_seconds"]))
    slot_id = None
    deadline = time.monotonic() + min(20, settings.analysis_deadline_seconds)
    while slot_id is None and time.monotonic() < deadline:
        slot_id = acquire_slot(settings, "job-probe")
        if slot_id is None:
            time.sleep(0.2)
    if slot_id is None:
        fail("ENGINE_ERROR", "Analysis capacity is in use.", retryable=True)
    def timed_out(signum, frame):
        fail("JOB_TIMEOUT", "Source analysis exceeded its deadline.", retryable=True)
    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, settings.analysis_deadline_seconds)
    try:
        conn = connect(settings)
        try:
            assert_no_cooldown(conn)
        finally:
            conn.close()
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        release_slot(settings, slot_id)


def _fixture_info(payload: dict[str, Any]) -> dict[str, Any]:
    catalog = _catalog(payload)
    video_id = payload["video_id"]
    entry = catalog.get(video_id)
    if not entry:
        fail("SOURCE_UNAVAILABLE", "Fixture source is not in the catalog.")
    streams = entry.get("streams")
    if not streams and entry.get("file"):
        streams = streams_from_file(Path(entry["file"]), payload)
    return {
        "video_id": video_id,
        "title": entry.get("title") or video_id,
        "channel": entry.get("channel") or "Fixture",
        "duration": entry.get("duration"),
        "live_status": entry.get("live_status") or "not_live",
        "availability": entry.get("availability") or "public",
        "thumbnail": None,
        "drm": bool(entry.get("drm")),
        "streams": streams or [],
    }


def _reject_ineligible(info: dict[str, Any], payload: dict[str, Any] | None = None) -> None:
    if (payload or {}).get("max_source_duration_seconds") and info.get("duration") and float(info["duration"]) > float(payload["max_source_duration_seconds"]):
        fail("LIMIT_EXCEEDED", "The source duration exceeds the configured limit.")
    live = info.get("live_status")
    if live in {"is_live", "is_upcoming", "post_live"}:
        fail("SOURCE_UNAVAILABLE", "Live or upcoming videos are not accepted.")
    if info.get("drm"):
        fail("SOURCE_FORBIDDEN", "DRM-protected media is not accepted.")
    if info.get("availability") in {"private", "needs_auth"}:
        fail("SOURCE_AUTH_REQUIRED", "Login is required.")
    if info.get("availability") in {"subscriber_only", "premium_only"}:
        fail("SOURCE_FORBIDDEN", "Restricted video.")


def _ffmpeg_finish(payload: dict[str, Any], sources: list[Path], resolved: dict[str, Any] | None = None) -> dict[str, Any] | None:
    contract = dict(payload["contract"])
    output = Path(payload["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    if payload.get("allow_test_hooks") and payload.get("test_hook") == "empty":
        output.write_bytes(b"")
        return
    if payload.get("allow_test_hooks") and payload.get("test_hook") == "text":
        output.write_text("not media", encoding="utf-8")
        return
    from app.config import load_settings
    from app.engine.ffmpeg_ops import build_command

    settings = _settings_with_tools(load_settings(), payload)
    progress = Path(payload["work_dir"]) / "ffmpeg.progress"
    single = len(sources) == 1
    audio_index = 0
    if single and resolved and resolved.get("audio") is not None:
        audio_index = int(resolved["audio"].get("audio_index") or 0)
    from app.services.media_validate import probe as inspect_media, validate_output, duration_tolerance
    inspected_durations = []
    for source in sources:
        fresh_duration = (inspect_media(settings, source).get("format") or {}).get("duration")
        if fresh_duration not in (None, "N/A"):
            inspected_durations.append(float(fresh_duration))
    if inspected_durations:
        fresh_duration = inspected_durations[0]
        if contract.get("duration") and abs(fresh_duration - float(contract["duration"])) > duration_tolerance(float(contract["duration"])):
            fail("FORMAT_CHANGED", "Source duration changed; analyze the link again.")
        contract["duration"] = fresh_duration
    cmd = build_command(settings, contract, sources, output, progress)
    if single:
        _apply_audio_map(cmd, audio_index)
    code = _run_ffmpeg(cmd, progress, contract.get("duration"), int(payload.get("ffmpeg_timeout") or 1800), _phase_name(contract))
    if code != 0 or not output.exists() or output.stat().st_size <= 0:
        fail("POSTPROCESS_FAILED", "ffmpeg failed.", retryable=False)
    emit({"type": "progress", "phase": "verifying", "component": "output", "downloaded_bytes": None,
          "total_bytes": None, "total_is_estimate": False, "speed_bps": None, "eta_seconds": None, "percent": None})
    checked = validate_output(settings, output, contract)
    original_duration = payload["contract"].get("duration")
    if original_duration and abs(checked["duration"] - float(original_duration)) > duration_tolerance(float(original_duration)):
        fail("OUTPUT_INVALID", "Output duration does not match the selected contract.")
    return checked


def _apply_audio_map(cmd: list[str], audio_index: int) -> None:
    if audio_index <= 0:
        return
    for index, token in enumerate(cmd):
        if token in {"0:a:0", "1:a:0"}:
            cmd[index] = token[:-1] + str(audio_index)


def _settings_with_tools(settings, payload):
    from dataclasses import replace

    return replace(
        settings,
        ffmpeg_path=payload.get("ffmpeg") or settings.ffmpeg_path,
        ffprobe_path=payload.get("ffprobe") or settings.ffprobe_path,
        deno_path=payload.get("deno") or settings.deno_path,
    )


def _phase_name(contract: dict[str, Any]) -> str:
    if contract.get("kind") == "mp4" and not contract.get("conversion"):
        return "merging"
    if contract.get("kind") == "mp3" or contract.get("conversion"):
        return "transcoding"
    return "merging"


def _run_ffmpeg(cmd: list[str], progress: Path, duration: float | None, timeout: int, phase: str) -> int:
    """Drain bounded pipes incrementally; no growing progress file or stderr log."""
    import selectors
    import subprocess
    from app.config import load_settings

    command = list(cmd)
    command[command.index("-progress") + 1] = "pipe:1"
    limit = max(1, min(load_settings().log_max_bytes, 256 * 1024))
    tail = bytearray()
    pending = b""
    values = {}
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, "progress")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    started = time.monotonic()
    try:
        while selector.get_map():
            if time.monotonic() - started > timeout:
                proc.kill()
                proc.wait(timeout=5)
                return 124
            for key, _ in selector.select(timeout=0.2):
                block = os.read(key.fileobj.fileno(), 8192)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stderr":
                    tail.extend(block)
                    if len(tail) > limit:
                        del tail[:-limit]
                    continue
                pending += block
                while b"\n" in pending:
                    raw, pending = pending.split(b"\n", 1)
                    text = raw.decode("utf-8", errors="replace")
                    if "=" in text:
                        name, value = text.split("=", 1)
                        values[name] = value
                        if name == "progress":
                            _emit_ffmpeg_values(values, duration, phase)
                            values = {}
                pending = pending[-8192:]
        return proc.wait(timeout=5)
    finally:
        selector.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for handle in (proc.stdout, proc.stderr):
            if handle:
                handle.close()
        progress.with_suffix(".err").write_bytes(tail)


def _emit_ffmpeg_values(values: dict[str, str], duration: float | None, phase: str) -> None:
    import math
    elapsed = _clock_seconds(values.get("out_time", ""))
    if elapsed is None:
        try:
            elapsed = max(0, int(values.get("out_time_us", ""))) / 1_000_000
        except ValueError:
            elapsed = None
    speed = None
    try:
        measured = float(values.get("speed", "").rstrip("x"))
        if math.isfinite(measured) and measured > 0:
            speed = measured
    except ValueError:
        pass
    percent = eta = None
    if elapsed is not None and duration and duration > 0:
        percent = max(0.0, min(100.0, elapsed / float(duration) * 100))
        if speed is not None:
            eta = max(0.0, float(duration) - elapsed) / speed
    emit({"type": "progress", "phase": phase, "component": "output", "downloaded_bytes": None,
          "total_bytes": None, "total_is_estimate": False, "speed_bps": None,
          "processing_speed": speed, "eta_seconds": eta, "percent": percent})


def _emit_ffmpeg_progress(progress: Path, duration: float | None, phase: str) -> None:
    """Compatibility helper: inspect at most the last 8 KiB, never the full log."""
    try:
        with progress.open("rb") as handle:
            handle.seek(max(0, progress.stat().st_size - 8192))
            lines = handle.read(8192).decode("utf-8", errors="replace").splitlines()
    except OSError:
        return
    _emit_ffmpeg_values(dict(line.split("=", 1) for line in lines if "=" in line), duration, phase)


def _clock_seconds(value: str) -> float | None:
    try:
        hours, minutes, seconds = value.strip().split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def _consume_script(payload: dict[str, Any], key: str) -> str | None:
    catalog = _catalog(payload)
    video_id = payload.get("video_id")
    entry = catalog.get(video_id) or {}
    script = entry.get(key) or []
    if not script:
        return None
    state = Path(payload["catalog"]).parent / "state" / f"{video_id}.{key}"
    state.parent.mkdir(parents=True, exist_ok=True)
    count = int(state.read_text(encoding="utf-8")) if state.exists() else 0
    code = script[min(count, len(script) - 1)]
    state.write_text(str(count + 1), encoding="utf-8")
    if code != "ok":
        retryable = code in {"HTTP_403", "ENGINE_ERROR"}
        fail(code, f"Fixture reported {code}.", retryable=retryable)
    return code


def _catalog(payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(payload["catalog"])
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_probe(payload: dict[str, Any]) -> dict[str, Any]:
    _consume_script(payload, "probe_script")
    catalog = _catalog(payload)
    video_id = payload["video_id"]
    entry = catalog.get(video_id)
    if not entry:
        fail("SOURCE_UNAVAILABLE", "Fixture source is not in the catalog.")
    if entry.get("live_status") in {"is_live", "is_upcoming"}:
        return {
            "video_id": video_id,
            "title": entry.get("title") or video_id,
            "channel": entry.get("channel") or "Fixture",
            "duration": entry.get("duration"),
            "live_status": entry["live_status"],
            "availability": entry.get("availability") or "public",
            "thumbnail": None,
            "drm": bool(entry.get("drm")),
            "streams": entry.get("streams") or [],
        }
    streams = entry.get("streams")
    if not streams and entry.get("file"):
        streams = streams_from_file(Path(entry["file"]), payload)
    return {
        "video_id": video_id,
        "title": entry.get("title") or video_id,
        "channel": entry.get("channel") or "Fixture",
        "duration": entry.get("duration"),
        "live_status": entry.get("live_status") or "not_live",
        "availability": entry.get("availability") or "public",
        "thumbnail": None,
        "drm": bool(entry.get("drm")),
        "streams": streams or [],
        "ignored_timestamp": False,
    }


def fixture_playlist(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    catalog = _catalog(payload)
    entry = catalog.get(payload.get("playlist_id") or "")
    items = (entry or {}).get("entries") or []
    # Stop at the cap. Do not scan further entries to replace inaccessible ones.
    selected = items[:limit]
    return {"entries": selected, "limit": limit, "stopped": len(items) > limit, "fetched": len(selected)}


def fixture_materialize(payload: dict[str, Any], work: Path) -> Path:
    entry = _catalog(payload)[payload["video_id"]]
    sleep_for = float(entry.get("sleep_seconds") or 0)
    if sleep_for:
        emit(
            {
                "type": "progress",
                "phase": "downloading",
                "downloaded_bytes": 0,
                "total_bytes": None,
                "total_is_estimate": False,
                "speed_bps": None,
                "eta_seconds": None,
                "percent": None,
            }
        )
        time.sleep(sleep_for)
    _consume_script(payload, "job_script")
    source = Path(entry["file"])
    target = work / f"input{source.suffix}"
    shutil.copyfile(source, target)
    emit(
        {
            "type": "progress",
            "phase": "downloading",
            "downloaded_bytes": target.stat().st_size,
            "total_bytes": target.stat().st_size,
            "total_is_estimate": False,
            "speed_bps": None,
            "eta_seconds": 0,
            "percent": 100,
        }
    )
    payload["test_hook"] = entry.get("test_hook")
    return target


def streams_from_file(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    from app.config import load_settings
    from app.services.media_validate import probe

    settings = _settings_with_tools(load_settings(), payload)
    info = probe(settings, path)
    streams: list[dict[str, Any]] = []
    audio_i = 0
    videos = [s for s in info.get("streams") or [] if s.get("codec_type") == "video"]
    audios = [s for s in info.get("streams") or [] if s.get("codec_type") == "audio"]
    if len(videos) == 1 and len(audios) == 1:
        video = videos[0]
        audio = audios[0]
        streams.append(_ff_stream("muxed", video, audio, 0))
        streams[0].update(filesize=path.stat().st_size, physical_input_key="fixture-file")
        return streams
    for video in videos:
        streams.append(_ff_stream("video", video, None, None))
    for audio in audios:
        streams.append(_ff_stream("audio", None, audio, audio_i))
        audio_i += 1
    for stream in streams:
        stream.update(filesize=path.stat().st_size, physical_input_key="fixture-file")
    return streams


def _ff_stream(kind: str, video: dict | None, audio: dict | None, audio_index: int | None) -> dict[str, Any]:
    tags = {}
    if audio:
        tags = audio.get("tags") or {}
    language = tags.get("language") or tags.get("LANGUAGE")
    if language in {"und", "unk"}:
        language = None
    return {
        "kind": kind,
        "vcodec": (video or {}).get("codec_name"),
        "acodec": (audio or {}).get("codec_name"),
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "fps": _fps(video),
        "rotation": __import__("app.services.media_validate", fromlist=["media_rotation"]).media_rotation(video or {}),
        "pix_fmt": (video or {}).get("pix_fmt"),
        "bit_depth": _depth(video),
        "dynamic_range": "sdr",
        "color_transfer": (video or {}).get("color_transfer"),
        "color_primaries": (video or {}).get("color_primaries"),
        "language": language,
        "role": "default" if audio_index in {None, 0} else "alternate",
        "audio_index": audio_index if audio_index is not None else 0,
        "filesize": None,
        "abr": (int((audio or {}).get("bit_rate") or 0) / 1000) or None,
        "ext": None,
        "format_id": f"{kind}-{audio_index or 0}",
    }


def _fps(video: dict | None) -> float | None:
    if not video:
        return None
    raw = video.get("avg_frame_rate") or video.get("r_frame_rate")
    if not raw or raw == "0/0":
        return None
    num, den = raw.split("/")
    if float(den) == 0:
        return None
    return float(num) / float(den)


def _depth(video: dict | None) -> int | None:
    if not video:
        return None
    raw = video.get("bits_per_raw_sample")
    return int(raw) if raw else None


def ytdlp_base(payload: dict[str, Any], *, download: bool) -> dict[str, Any]:
    deno = payload.get("deno")
    ffmpeg = payload.get("ffmpeg")
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 0,
        "fragment_retries": 0,
        "extractor_retries": 0,
        "file_access_retries": 0,
        "ignoreerrors": False,
        "allowed_extractors": ["youtube"],
        "remote_components": set(),
        "js_runtimes": {"deno": {"path": deno} if deno else {}},
        "no_color": True,
        "socket_timeout": 20,
    }
    if ffmpeg:
        opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
    if download:
        opts["noprogress"] = True
    return opts


def ytdlp_probe(payload: dict[str, Any], *, download: bool) -> dict[str, Any]:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    opts = ytdlp_base(payload, download=False)
    url = payload["url"]
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        code, retryable = classify_message(str(exc))
        fail(code, "The source could not be read.", retryable=retryable, retry_after=_retry_after(exc) if code == "SOURCE_RATE_LIMITED" else None)
    if not info:
        fail("SOURCE_UNAVAILABLE", "No source information was returned.")
    return sanitize_info(info, payload.get("video_id"), include_download=payload.get("action") == "job")


def sanitize_info(info: dict[str, Any], expected_id: str | None, *, include_download: bool = False) -> dict[str, Any]:
    video_id = info.get("id")
    if expected_id and video_id and video_id != expected_id:
        fail("SOURCE_UNAVAILABLE", "The extractor returned a different video.")
    live = info.get("live_status") or ("is_live" if info.get("is_live") else "not_live")
    streams = []
    for fmt in info.get("formats") or []:
        if fmt.get("has_drm"):
            continue
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        if vcodec in (None, "none") and acodec in (None, "none"):
            continue
        if vcodec not in (None, "none") and acodec not in (None, "none"):
            kind = "muxed"
        elif vcodec not in (None, "none"):
            kind = "video"
        else:
            kind = "audio"
        note = fmt.get("format_note") or ""
        preference = fmt.get("language_preference")
        if isinstance(preference, int) and preference >= 10 or "original" in note.lower():
            role = "original"
        elif isinstance(preference, int) and preference >= 5 or "(default)" in note.lower():
            role = "default"
        else:
            role = "alternate" if kind != "video" else None
        dynamic = str(fmt.get("dynamic_range") or "")
        hdr = "hdr" in dynamic.lower() or "HDR" in note or "HLG" in note
        vnorm = norm_vcodec(vcodec)
        pix = fmt.get("pix_fmt")
        depth = fmt.get("bit_depth")
        # YouTube's non-HDR H.264 ladder is 8-bit 4:2:0. ffprobe still has to confirm after download.
        if vnorm == "h264" and not hdr and not pix:
            pix = "yuv420p"
            depth = depth or 8
            dynamic = dynamic or "SDR"
        streams.append(
            {
                "format_id": str(fmt.get("format_id") or ""),
                "kind": kind,
                "vcodec": vcodec,
                "acodec": acodec,
                "width": fmt.get("width"),
                "height": fmt.get("height"),
                "fps": fmt.get("fps"),
                "pix_fmt": pix,
                "bit_depth": depth,
                "dynamic_range": "hdr" if hdr else ("sdr" if dynamic else "unknown"),
                "color_transfer": fmt.get("color_transfer"),
                "color_primaries": fmt.get("color_primaries"),
                "language": fmt.get("language"),
                "role": role,
                "note": note,
                "filesize": fmt.get("filesize"),
                "filesize_approx": fmt.get("filesize_approx"),
                "size_provenance": "exact" if fmt.get("filesize") else ("approximate" if fmt.get("filesize_approx") else "unknown"),
                "audio_track_id": (fmt.get("audio_track") or {}).get("id") if isinstance(fmt.get("audio_track"), dict) else fmt.get("audio_track_id"),
                "rotation": fmt.get("rotation") or 0,
                "tbr": fmt.get("tbr"),
                "asr": fmt.get("asr"),
                "audio_channels": fmt.get("audio_channels"),
                "protocol": fmt.get("protocol"),
                "abr": fmt.get("abr"),
                "ext": fmt.get("ext"),
                "audio_index": 0,
            }
        )
        if include_download:
            # Transient child-only source data. Never serialized into analysis,
            # durable contracts, API responses or diagnostic messages.
            download_info = {key: value for key, value in info.items() if key not in {"formats", "thumbnails", "requested_formats", "requested_downloads"}}
            download_info.update(fmt)
            streams[-1]["_download_info"] = download_info
    thumb = None
    for item in info.get("thumbnails") or []:
        candidate = item.get("url")
        if isinstance(candidate, str) and candidate.startswith("https://"):
            host = candidate.split("/")[2].split(":")[0]
            if host in {"i.ytimg.com", "i9.ytimg.com", "yt3.ggpht.com", "img.youtube.com"}:
                thumb = candidate.split("?", 1)[0]
    return {
        "video_id": video_id,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": info.get("duration"),
        "live_status": live,
        "availability": info.get("availability") or "public",
        "thumbnail": thumb,
        "drm": bool(info.get("is_drm")),
        "streams": streams,
    }


def ytdlp_playlist(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    opts = ytdlp_base(payload, download=False)
    opts["noplaylist"] = False
    opts["extract_flat"] = "in_playlist"
    opts["playliststart"] = 1
    opts["playlistend"] = limit
    opts["lazy_playlist"] = True
    opts["allowed_extractors"] = ["youtube", "youtube:tab", "youtube:playlist"]
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(payload["url"], download=False)
    except DownloadError as exc:
        code, retryable = classify_message(str(exc))
        fail(code, "The playlist could not be read.", retryable=retryable, retry_after=_retry_after(exc) if code == "SOURCE_RATE_LIMITED" else None)
    entries = []
    raw_entries = info.get("entries") if info else None
    if raw_entries is None:
        raw_entries = []
    for index, entry in enumerate(raw_entries):
        if index >= limit:
            break
        if entry is None:
            entries.append({"position": index + 1, "video_id": None, "title": None, "available": False, "reason": "unavailable"})
            continue
        video_id = entry.get("id")
        entries.append(
            {
                "position": index + 1,
                "video_id": video_id if isinstance(video_id, str) and len(video_id) == 11 else None,
                "title": entry.get("title"),
                "available": bool(video_id),
                "reason": None if video_id else "unavailable",
                "canonical_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
            }
        )
    return {"entries": entries, "limit": limit, "stopped": True, "fetched": len(entries)}


def ytdlp_download(payload: dict[str, Any], work: Path, resolved: dict[str, Any]) -> list[Path]:
    targets = [s for s in (resolved.get("video"), resolved.get("audio")) if s is not None]
    return [_download_one(payload, work, stream, index + 1, len(targets)) for index, stream in enumerate(targets)]


def _download_one(payload: dict[str, Any], work: Path, stream: dict[str, Any], component_index: int = 1, component_count: int = 1) -> Path:
    import re
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    format_id = str(stream.get("format_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", format_id):
        fail("FORMAT_UNAVAILABLE", "The resolved format id was rejected.")
    if not stream.get("_download_info"):
        fail("FORMAT_CHANGED", "Fresh source information is required.")
    if payload.get("manage_slot"):
        from app.config import load_settings
        from app.db import connect
        from app.services.analysis import assert_no_cooldown
        conn = connect(load_settings())
        try:
            assert_no_cooldown(conn)
        finally:
            conn.close()
    opts = ytdlp_base(payload, download=True)
    opts["outtmpl"] = str(work / f"{format_id}.%(ext)s")
    opts["overwrites"] = True
    component = "audio" if stream.get("kind") == "audio" else ("muxed" if stream.get("kind") == "muxed" else "video")

    def hook(event: dict[str, Any]) -> None:
        if event.get("status") not in {"downloading", "finished"}:
            return
        exact, estimate = event.get("total_bytes"), event.get("total_bytes_estimate")
        got = event.get("downloaded_bytes") or 0
        emit({"type": "progress", "phase": "downloading", "component": component,
              "component_index": component_index, "component_count": component_count,
              "downloaded_bytes": got, "total_bytes": exact if exact is not None else estimate,
              "total_is_estimate": exact is None and estimate is not None,
              "speed_bps": event.get("speed"), "eta_seconds": event.get("eta"),
              "percent": (max(0, min(100, got / exact * 100))) if exact else None})
    opts["progress_hooks"] = [hook]
    try:
        with YoutubeDL(opts) as ydl:
            # process_info downloads the just-resolved selected representation;
            # download([url]) would perform a second unbounded extraction.
            info = dict(stream["_download_info"])
            target = Path(ydl.prepare_filename(info))
            ydl.process_info(info)
    except DownloadError as exc:
        code, retryable = classify_message(str(exc))
        fail(code, "The download failed.", retryable=retryable, retry_after=_retry_after(exc) if code == "SOURCE_RATE_LIMITED" else None)
    if not target.is_file() or target.suffix in {".part", ".ytdl"}:
        fail("ENGINE_ERROR", "The download finished without a file.", retryable=True)
    return target


if __name__ == "__main__":
    main()
