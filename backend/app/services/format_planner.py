"""Track-aware output planning. Pure: no network and no ffmpeg."""

from __future__ import annotations

from typing import Any

from app.config import Settings

MP3_RATES = (128, 192, 320)


def norm_vcodec(value: str | None) -> str | None:
    if not value or value == "none":
        return None
    token = value.lower().split(" ")[0]
    if token.startswith(("avc1", "h264")):
        return "h264"
    if token.startswith(("vp9", "vp09")):
        return "vp9"
    if token.startswith("av01"):
        return "av1"
    if token.startswith(("hev1", "hvc1", "hevc")):
        return "hevc"
    return token.split(".")[0]


def norm_acodec(value: str | None) -> str | None:
    if not value or value == "none":
        return None
    token = value.lower()
    if token.startswith(("mp4a", "aac")):
        return "aac"
    if token.startswith("opus"):
        return "opus"
    if token.startswith("mp3"):
        return "mp3"
    if "vorbis" in token:
        return "vorbis"
    return token.split(".")[0]


def display_size(width: int, height: int, rotation: int = 0) -> tuple[int, int]:
    if rotation % 180 == 90:
        return height, width
    return width, height


def fits_cap(width: int, height: int, cap: int) -> bool:
    long_cap = {1080: 1920, 2160: 3840}.get(cap, int(round(cap * 16 / 9)))
    short, long_edge = min(width, height), max(width, height)
    return width > 0 and height > 0 and short <= cap and long_edge <= long_cap


def resolution_label(width: int, height: int) -> str:
    short = min(width, height)
    if short in {360, 480, 720, 1080, 1440, 2160}:
        return f"{short}p"
    return f"{width}×{height}"


def is_hdr(stream: dict[str, Any]) -> bool:
    if str(stream.get("dynamic_range") or "").lower() == "hdr":
        return True
    transfer = str(stream.get("color_transfer") or "").lower()
    primaries = str(stream.get("color_primaries") or "").lower()
    if transfer in {"smpte2084", "arib-std-b67"}:
        return True
    if primaries in {"bt2020"}:
        return True
    return False


def is_compatible_video(stream: dict[str, Any]) -> bool:
    if norm_vcodec(stream.get("vcodec")) != "h264":
        return False
    if is_hdr(stream):
        return False
    pix = stream.get("pix_fmt")
    depth = stream.get("bit_depth")
    if depth not in (None, 8):
        return False
    if pix not in {"yuv420p", "yuvj420p"}:
        return False
    if str(stream.get("dynamic_range") or "sdr").lower() == "unknown" and not pix:
        return False
    return True


def _audio_role(stream: dict[str, Any], index: int) -> str:
    explicit = str(stream.get("role") or "").lower()
    if explicit in {"original", "default", "alternate"}:
        return explicit
    note = " ".join(
        str(stream.get(key) or "")
        for key in ("note", "track_name", "format_note")
    ).lower()
    if stream.get("is_original") or "original" in note:
        return "original"
    if stream.get("is_default"):
        return "default"
    if index == 0:
        return "default"
    return "alternate"


def audio_tracks(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for index, stream in enumerate(streams):
        acodec = norm_acodec(stream.get("acodec"))
        if stream.get("kind") == "video" or not acodec:
            continue
        role = _audio_role(stream, index)
        language = stream.get("language") or None
        if language is not None:
            language = str(language)
        base = f"{language or ''}|{role}|{acodec}"
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else f"{base}|{seen[base]}"
        tracks.append(
            {
                "track_key": key,
                "language": language,
                "role": role,
                "acodec": acodec,
                "source_kind": stream.get("kind"),
                "source_index": index,
                "filesize": stream.get("filesize"),
                "abr": stream.get("abr"),
                "ext": stream.get("ext"),
            }
        )
    order = {"original": 0, "default": 1, "alternate": 2}
    tracks.sort(key=lambda item: (order.get(item["role"], 9), item["track_key"]))
    return tracks


def _video_view(stream: dict[str, Any]) -> dict[str, Any] | None:
    if stream.get("kind") == "audio":
        return None
    vcodec = norm_vcodec(stream.get("vcodec"))
    width = stream.get("width")
    height = stream.get("height")
    if not vcodec or not width or not height:
        return None
    dw, dh = display_size(int(width), int(height), int(stream.get("rotation") or 0))
    return {
        "vcodec": vcodec,
        "width": dw,
        "height": dh,
        "fps": stream.get("fps"),
        "pix_fmt": stream.get("pix_fmt"),
        "bit_depth": stream.get("bit_depth"),
        "dynamic_range": stream.get("dynamic_range") or ("hdr" if is_hdr(stream) else "sdr"),
        "color_transfer": stream.get("color_transfer"),
        "filesize": stream.get("filesize"),
        "kind": stream.get("kind"),
        "acodec": norm_acodec(stream.get("acodec")),
        "language": stream.get("language"),
        "compatible": is_compatible_video({**stream, "vcodec": vcodec, "width": dw, "height": dh}),
        "hdr": is_hdr(stream),
    }


def plan_outputs(
    streams: list[dict[str, Any]],
    duration: float | None,
    settings: Settings,
    *,
    transcoding_enabled: bool | None = None,
) -> dict[str, Any]:
    enabled = settings.enable_transcoding if transcoding_enabled is None else transcoding_enabled
    videos = [view for view in (_video_view(stream) for stream in streams) if view]
    tracks = audio_tracks(streams)
    choices: list[dict[str, Any]] = []

    compatible = [
        video
        for video in videos
        if video["compatible"] and fits_cap(video["width"], video["height"], settings.native_mp4_cap)
    ]
    # One choice per distinct resolution + audio track. Prefer larger pixel count.
    compatible.sort(key=lambda video: video["width"] * video["height"], reverse=True)
    seen_res: set[tuple[int, int, str]] = set()
    within_default: list[dict[str, Any]] = []
    for video in compatible:
        if not tracks and video["acodec"] not in {None, "aac"} and video["kind"] != "video":
            continue
        audio_options = tracks or ([None] if video["kind"] == "muxed" and video["acodec"] == "aac" else [])
        if video["kind"] == "video" and not tracks:
            audio_options = [None]
        for track in audio_options:
            # Separate video needs an AAC track. Muxed already carrying non-AAC is not a copy.
            if video["kind"] == "muxed" and video["acodec"] != "aac":
                continue
            if track and track["acodec"] != "aac":
                continue
            key = (video["width"], video["height"], track["track_key"] if track else "")
            if key in seen_res:
                continue
            seen_res.add(key)
            estimate = _sum_size(video.get("filesize"), track.get("filesize") if track else None)
            choice = _choice(
                kind="mp4",
                conversion=False,
                consent=False,
                container="mp4",
                ext="mp4",
                mime="video/mp4",
                video=video,
                track=track,
                output_vcodec="h264",
                output_acodec="aac" if track or video["acodec"] == "aac" else None,
                has_audio=bool(track or video["acodec"] == "aac"),
                duration=duration,
                estimate=estimate,
                estimate_flag=False,
                label=resolution_label(video["width"], video["height"]),
            )
            choices.append(choice)
            if fits_cap(video["width"], video["height"], settings.default_mp4_cap):
                within_default.append(choice)

    if within_default:
        best = max(within_default, key=lambda item: (item["output_width"] or 0) * (item["output_height"] or 0))
        for choice in choices:
            if choice is best:
                choice["is_default"] = True
                choice["label"] = "Best compatible MP4 within limit"
                choice["resolution_label"] = resolution_label(choice["output_width"], choice["output_height"])

    if enabled:
        sdr_sources = [video for video in videos if not video["hdr"] and video["dynamic_range"] != "unknown"]
        # Unknown HDR characteristics are not eligible for silent conversion.
        sdr_sources = [video for video in sdr_sources if not video["hdr"]]
        if sdr_sources and (tracks or any(video["acodec"] for video in sdr_sources)):
            source = max(sdr_sources, key=lambda video: video["width"] * video["height"])
            ow, oh = _fit_box(source["width"], source["height"], settings.conversion_cap)
            audio_options = [track for track in tracks] or [None]
            for track in audio_options:
                if track is None and not source["acodec"]:
                    continue
                already = any(
                    item["kind"] == "mp4"
                    and not item["conversion"]
                    and item["output_width"] == ow
                    and item["output_height"] == oh
                    and item.get("audio_track_key") == (track["track_key"] if track else None)
                    for item in choices
                )
                if already and source["compatible"]:
                    continue
                choices.append(
                    _choice(
                        kind="mp4",
                        conversion=True,
                        consent=True,
                        container="mp4",
                        ext="mp4",
                        mime="video/mp4",
                        video=source,
                        track=track,
                        output_vcodec="h264",
                        output_acodec="aac",
                        has_audio=True if track or source["acodec"] else False,
                        duration=duration,
                        estimate=None,
                        estimate_flag=True,
                        label="Convert to compatible MP4",
                        output_size=(ow, oh),
                    )
                )

    for track in tracks:
        for rate in MP3_RATES:
            estimate = int(duration * rate * 1000 / 8) if duration else None
            choice = _choice(
                kind="mp3",
                conversion=False,
                consent=False,
                container="mp3",
                ext="mp3",
                mime="audio/mpeg",
                video=None,
                track=track,
                output_vcodec=None,
                output_acodec="mp3",
                has_audio=True,
                duration=duration,
                estimate=estimate,
                estimate_flag=True,
                label=f"MP3 {rate} kbps",
                mp3_bitrate=rate,
            )
            choice["is_default"] = rate == settings.mp3_default_kbps and track is tracks[0]
            choices.append(choice)
        original = _original_container(track["acodec"])
        if original:
            ext, mime = original
            choices.append(
                _choice(
                    kind="original_audio",
                    conversion=False,
                    consent=False,
                    container=ext,
                    ext=ext,
                    mime=mime,
                    video=None,
                    track=track,
                    output_vcodec=None,
                    output_acodec=track["acodec"],
                    has_audio=True,
                    duration=duration,
                    estimate=track.get("filesize"),
                    estimate_flag=False,
                    label=f"Original {track['acodec'].upper()}",
                )
            )

    return {
        "audio_tracks": [
            {
                "track_key": track["track_key"],
                "language": track["language"],
                "role": track["role"],
                "codec": track["acodec"],
            }
            for track in tracks
        ],
        "choices": choices,
    }


def _original_container(acodec: str) -> tuple[str, str] | None:
    return {
        "aac": ("m4a", "audio/mp4"),
        "opus": ("webm", "audio/webm"),
        "mp3": ("mp3", "audio/mpeg"),
        "vorbis": ("ogg", "audio/ogg"),
    }.get(acodec)


def _fit_box(width: int, height: int, cap: int) -> tuple[int, int]:
    long_cap = {1080: 1920, 2160: 3840}.get(cap, int(round(cap * 16 / 9)))
    scale = min(1.0, cap / min(width, height), long_cap / max(width, height))
    tw = max(2, int(width * scale) // 2 * 2)
    th = max(2, int(height * scale) // 2 * 2)
    return tw, th


def _sum_size(*parts: int | None) -> int | None:
    if any(part is None for part in parts):
        return None
    return int(sum(part or 0 for part in parts))


def _choice(
    *,
    kind: str,
    conversion: bool,
    consent: bool,
    container: str,
    ext: str,
    mime: str,
    video: dict[str, Any] | None,
    track: dict[str, Any] | None,
    output_vcodec: str | None,
    output_acodec: str | None,
    has_audio: bool,
    duration: float | None,
    estimate: int | None,
    estimate_flag: bool,
    label: str,
    mp3_bitrate: int | None = None,
    output_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    ow = oh = None
    if output_size:
        ow, oh = output_size
    elif video:
        ow, oh = video["width"], video["height"]
    return {
        "kind": kind,
        "conversion": conversion,
        "requires_consent": consent,
        "container": container,
        "ext": ext,
        "mime": mime,
        "has_video": kind == "mp4",
        "has_audio": has_audio,
        "output_width": ow,
        "output_height": oh,
        "output_fps": video.get("fps") if video else None,
        "output_vcodec": output_vcodec,
        "output_acodec": output_acodec,
        "input_vcodec": video.get("vcodec") if video else None,
        "input_width": video.get("width") if video else None,
        "input_height": video.get("height") if video else None,
        "input_fps": video.get("fps") if video else None,
        "input_acodec": (track or {}).get("acodec") if track else (video.get("acodec") if video else None),
        "audio_track_key": track["track_key"] if track else None,
        "audio_language": track["language"] if track else (video.get("language") if video else None),
        "audio_role": track["role"] if track else None,
        "mp3_bitrate": mp3_bitrate,
        "duration": duration,
        "label": label,
        "resolution_label": resolution_label(ow, oh) if ow and oh else None,
        "size_estimate": estimate,
        "size_is_estimate": estimate_flag if estimate is not None else True,
        "portrait": bool(ow and oh and oh > ow),
        "is_default": False,
        "input_dynamic_range": video.get("dynamic_range") if video else None,
    }
