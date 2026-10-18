"""Re-resolve a saved output contract against a fresh probe. No silent downgrade."""

from __future__ import annotations

from typing import Any

from app.services.format_planner import fits_cap, is_hdr, norm_acodec, norm_vcodec


def _close(left: float | None, right: float | None, tol: float = 0.2) -> bool:
    if left is None or right is None:
        return left is None or right is None
    return abs(float(left) - float(right)) <= tol


def _video_candidates(streams: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for stream in streams:
        if stream.get("kind") == "audio":
            continue
        if norm_vcodec(stream.get("vcodec")) != contract.get("input_vcodec"):
            continue
        if int(stream.get("width") or 0) != int(contract.get("input_width") or 0):
            continue
        if int(stream.get("height") or 0) != int(contract.get("input_height") or 0):
            continue
        if not _close(stream.get("fps"), contract.get("input_fps")):
            continue
        if contract.get("conversion"):
            if is_hdr(stream) or str(stream.get("dynamic_range") or "").lower() in {"hdr", "unknown"}:
                continue
            found.append(stream)
        else:
            if norm_vcodec(stream.get("vcodec")) != "h264":
                continue
            if stream.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
                continue
            if is_hdr(stream):
                continue
            found.append(stream)
    return found


def _audio_candidates(streams: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    key = contract.get("audio_track_key")
    wanted = contract.get("input_acodec")
    found = []
    for stream in streams:
        if stream.get("kind") == "video":
            continue
        if norm_acodec(stream.get("acodec")) != wanted:
            continue
        if key and stream.get("track_key") != key:
            continue
        language = stream.get("language")
        if contract.get("audio_language") and language and language != contract.get("audio_language"):
            continue
        found.append(stream)
    return found


def resolve_contract(streams: list[dict[str, Any]], contract: dict[str, Any], native_cap: int) -> dict[str, Any] | None:
    """Return download instructions, or None when the contract no longer holds."""
    prepared = _with_track_keys(streams)
    if contract.get("kind") == "mp4":
        if contract.get("output_width") and contract.get("output_height"):
            if not contract.get("conversion") and not fits_cap(
                int(contract["output_width"]), int(contract["output_height"]), native_cap
            ):
                return None
        videos = _video_candidates(prepared, contract)
        if not videos:
            return None
        video = videos[0]
        audio = None
        if contract.get("has_audio"):
            audios = _audio_candidates(prepared, contract)
            # A muxed source can satisfy audio itself.
            if video.get("kind") == "muxed" and norm_acodec(video.get("acodec")) == contract.get("input_acodec"):
                if not contract.get("audio_track_key") or video.get("track_key") == contract.get("audio_track_key"):
                    audio = video
            if audio is None:
                separate = [item for item in audios if item is not video]
                if not separate:
                    return None
                audio = separate[0]
        return {"video": video, "audio": None if audio is video else audio, "muxed": audio is video}
    if contract.get("kind") in {"mp3", "original_audio"}:
        audios = _audio_candidates(prepared, contract)
        if not audios:
            return None
        # Prefer a dedicated audio stream over a muxed one when both match.
        audios.sort(key=lambda item: 0 if item.get("kind") == "audio" else 1)
        return {"video": None, "audio": audios[0], "muxed": audios[0].get("kind") == "muxed"}
    return None


def _with_track_keys(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.services.format_planner import audio_tracks

    keyed = {track["source_index"]: track["track_key"] for track in audio_tracks(streams)}
    enriched = []
    for index, stream in enumerate(streams):
        copy = dict(stream)
        if index in keyed:
            copy["track_key"] = keyed[index]
        enriched.append(copy)
    return enriched
