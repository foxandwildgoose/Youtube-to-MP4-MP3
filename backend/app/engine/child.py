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


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str, *, retryable: bool = False) -> None:
    emit({"type": "error", "code": code, "message": message, "retryable": retryable})
    raise SystemExit(2)


def classify_message(text: str) -> tuple[str, bool]:
    lowered = text.lower()
    if "429" in text or "too many request" in lowered or "rate limit" in lowered:
        retry_after = None
        for token in text.split():
            if token.isdigit() and "retry" in lowered:
                retry_after = int(token)
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
            run_job(payload)
            emit({"type": "result", "ok": True, "output": payload["output_path"]})
        else:
            fail("ENGINE_ERROR", "Unknown engine action.")
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — last-resort boundary of the subprocess
        code, retryable = classify_message(str(exc))
        fail(code, "The media engine failed.", retryable=retryable)


def probe(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("adapter") == "fixture":
        return fixture_probe(payload)
    return ytdlp_probe(payload, download=False)


def playlist(payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("playlist_limit") or 20)
    if payload.get("adapter") == "fixture":
        return fixture_playlist(payload, limit)
    return ytdlp_playlist(payload, limit)


def run_job(payload: dict[str, Any]) -> None:
    work = Path(payload["work_dir"])
    work.mkdir(parents=True, exist_ok=True)

    def load_info() -> dict[str, Any]:
        if payload.get("adapter") == "fixture":
            return _fixture_info(payload)
        info = ytdlp_probe(payload, download=False)
        _reject_ineligible(info)
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
    _ffmpeg_finish(payload, sources, resolved)


def _with_slot(payload: dict[str, Any], fn):
    if not payload.get("manage_slot"):
        return fn()
    from app.config import load_settings
    from app.services.slots import acquire_slot, release_slot

    settings = load_settings()
    slot_id = None
    deadline = time.monotonic() + 20
    while slot_id is None and time.monotonic() < deadline:
        slot_id = acquire_slot(settings, "job-probe")
        if slot_id is None:
            time.sleep(0.2)
    if slot_id is None:
        fail("LIMIT_EXCEEDED", "Analysis capacity is in use.", retryable=True)
    try:
        return fn()
    finally:
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


def _reject_ineligible(info: dict[str, Any]) -> None:
    live = info.get("live_status")
    if live in {"is_live", "is_upcoming", "post_live"}:
        fail("SOURCE_UNAVAILABLE", "Live or upcoming videos are not accepted.")
    if info.get("drm"):
        fail("SOURCE_FORBIDDEN", "DRM-protected media is not accepted.")
    if info.get("availability") in {"private", "needs_auth"}:
        fail("SOURCE_AUTH_REQUIRED", "Login is required.")
    if info.get("availability") in {"subscriber_only", "premium_only"}:
        fail("SOURCE_FORBIDDEN", "Restricted video.")


def _ffmpeg_finish(payload: dict[str, Any], sources: list[Path], resolved: dict[str, Any] | None = None) -> None:
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
    cmd = build_command(settings, contract, sources, output, progress)
    if single:
        _apply_audio_map(cmd, audio_index)
    code = _run_ffmpeg(cmd, progress, contract.get("duration"), int(payload.get("ffmpeg_timeout") or 1800), _phase_name(contract))
    if code != 0 or not output.exists() or output.stat().st_size <= 0:
        fail("POSTPROCESS_FAILED", "ffmpeg failed.", retryable=False)


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
    import subprocess

    err_path = progress.with_suffix(".err")
    with err_path.open("wb") as err_handle:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err_handle)
        started = time.monotonic()
        while proc.poll() is None:
            if time.monotonic() - started > timeout:
                proc.kill()
                proc.wait(timeout=5)
                return 124
            _emit_ffmpeg_progress(progress, duration, phase)
            time.sleep(0.2)
    return proc.returncode or 0


def _emit_ffmpeg_progress(progress: Path, duration: float | None, phase: str) -> None:
    if not progress.exists():
        return
    elapsed = None
    try:
        text = progress.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        if line.startswith("out_time="):
            elapsed = _clock_seconds(line.split("=", 1)[1])
        elif line.startswith("out_time_us=") and elapsed is None:
            try:
                elapsed = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                elapsed = None
        elif line.startswith("out_time_ms=") and elapsed is None:
            # Some builds mislabel microseconds as milliseconds. Prefer out_time.
            try:
                raw = int(line.split("=", 1)[1])
            except ValueError:
                continue
            as_ms = raw / 1000
            as_us = raw / 1_000_000
            elapsed = as_us if duration and as_ms > float(duration) * 2 else as_ms
    if elapsed is None:
        emit(
            {
                "type": "progress",
                "phase": phase,
                "downloaded_bytes": None,
                "total_bytes": None,
                "total_is_estimate": False,
                "speed_bps": None,
                "eta_seconds": None,
                "percent": None,
            }
        )
        return
    percent = None
    eta = None
    if duration and duration > 0:
        percent = max(0.0, min(99.0, elapsed / float(duration) * 100))
        eta = max(0.0, float(duration) - elapsed)
    emit(
        {
            "type": "progress",
            "phase": phase,
            "downloaded_bytes": None,
            "total_bytes": None,
            "total_is_estimate": False,
            "speed_bps": None,
            "eta_seconds": eta,
            "percent": percent,
        }
    )


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
        return streams
    for video in videos:
        streams.append(_ff_stream("video", video, None, None))
    for audio in audios:
        streams.append(_ff_stream("audio", None, audio, audio_i))
        audio_i += 1
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
        "pix_fmt": (video or {}).get("pix_fmt"),
        "bit_depth": _depth(video),
        "dynamic_range": "sdr",
        "color_transfer": (video or {}).get("color_transfer"),
        "color_primaries": (video or {}).get("color_primaries"),
        "language": language,
        "role": "default" if audio_index in {None, 0} else "alternate",
        "audio_index": audio_index if audio_index is not None else 0,
        "filesize": None,
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
        fail(code, "The source could not be read.", retryable=retryable)
    if not info:
        fail("SOURCE_UNAVAILABLE", "No source information was returned.")
    return sanitize_info(info, payload.get("video_id"))


def sanitize_info(info: dict[str, Any], expected_id: str | None) -> dict[str, Any]:
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
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                "abr": fmt.get("abr"),
                "ext": fmt.get("ext"),
                "audio_index": 0,
            }
        )
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
        fail(code, "The playlist could not be read.", retryable=retryable)
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
    targets = []
    video = resolved.get("video")
    audio = resolved.get("audio")
    if video and (resolved.get("muxed") or audio is None or audio is video):
        targets.append(video)
    else:
        if video:
            targets.append(video)
        if audio:
            targets.append(audio)
    if not targets and audio:
        targets.append(audio)
    return [_download_one(payload, work, str(item.get("format_id") or "")) for item in targets]


def _download_one(payload: dict[str, Any], work: Path, format_id: str) -> Path:
    import re

    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", format_id):
        fail("FORMAT_UNAVAILABLE", "The resolved format id was rejected.")
    opts = ytdlp_base(payload, download=True)
    dest_tmpl = str(work / f"{format_id}.%(ext)s")
    opts["format"] = format_id
    opts["outtmpl"] = dest_tmpl
    opts["overwrites"] = True
    downloaded = {"bytes": 0}

    def hook(event: dict[str, Any]) -> None:
        if event.get("status") != "downloading":
            return
        exact = event.get("total_bytes")
        estimate = event.get("total_bytes_estimate")
        got = event.get("downloaded_bytes") or 0
        downloaded["bytes"] = got
        total = exact or estimate
        emit(
            {
                "type": "progress",
                "phase": "downloading",
                "downloaded_bytes": got,
                "total_bytes": total,
                "total_is_estimate": exact is None and estimate is not None,
                "speed_bps": event.get("speed"),
                "eta_seconds": event.get("eta"),
                "percent": (got / exact * 100) if exact else None,
            }
        )

    opts["progress_hooks"] = [hook]
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([payload["url"]])
    except DownloadError as exc:
        code, retryable = classify_message(str(exc))
        fail(code, "The download failed.", retryable=retryable)
    matches = list(work.glob(f"{format_id}.*"))
    if not matches:
        fail("ENGINE_ERROR", "The download finished without a file.", retryable=True)
    return matches[0]


if __name__ == "__main__":
    main()
