"""Resolve an immutable semantic output contract against fresh source metadata."""
from __future__ import annotations

from typing import Any

from app.services.format_planner import (
    audio_tracks, fits_cap, frame_rate, is_compatible_video, is_hdr,
    norm_acodec, norm_language, norm_rotation, norm_vcodec, representation_rank,
)


def _close(left: Any, right: Any, tol: float = 0.2) -> bool:
    left, right = frame_rate(left), frame_rate(right)
    if right is None:
        return True  # No rate was promised when the source could not report one.
    return left is not None and abs(left - right) <= max(0.01, min(tol, right * 0.005))


def _video_candidates(streams: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for stream in streams:
        if stream.get('kind') == 'audio' or norm_vcodec(stream.get('vcodec')) != contract.get('input_vcodec'):
            continue
        if int(stream.get('width') or 0) != int(contract.get('input_width') or 0) or int(stream.get('height') or 0) != int(contract.get('input_height') or 0):
            continue
        if norm_rotation(stream.get('rotation')) != norm_rotation(contract.get('input_rotation')) or not _close(stream.get('fps'), contract.get('input_fps')):
            continue
        if contract.get('conversion'):
            if is_hdr(stream) or str(stream.get('dynamic_range') or 'unknown').lower() != 'sdr':
                continue
        elif not is_compatible_video(stream):
            continue
        found.append(stream)
    return sorted(found, key=lambda s: (float(s.get('tbr') or 0), str(s.get('format_id') or '')), reverse=True)


def _audio_candidates(streams: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    key, wanted, minimum = contract.get('audio_track_key'), contract.get('input_acodec'), contract.get('input_audio_min_kbps')
    found = []
    for stream in streams:
        if stream.get('kind') == 'video' or norm_acodec(stream.get('acodec')) != wanted:
            continue
        if key and key.startswith('track-') and stream.get('track_key') != key:
            continue
        # Legacy queued contracts used language|role|codec keys. They retain
        # their language/role/codec requirement without adopting an index suffix.
        if norm_language(stream.get('language')) != norm_language(contract.get('audio_language')):
            continue
        if contract.get('audio_role') and stream.get('logical_role') != contract['audio_role']:
            continue
        if minimum is not None and (stream.get('abr') is None or float(stream['abr']) + 0.5 < float(minimum)):
            continue
        found.append(stream)
    return sorted(found, key=representation_rank, reverse=True)


def resolve_contract(streams: list[dict[str, Any]], contract: dict[str, Any], native_cap: int) -> dict[str, Any] | None:
    prepared = _with_track_keys(streams)
    if contract.get('kind') == 'mp4':
        if not contract.get('conversion') and not fits_cap(int(contract.get('output_width') or 0), int(contract.get('output_height') or 0), native_cap):
            return None
        videos = _video_candidates(prepared, contract)
        if not videos:
            return None
        video, audio = videos[0], None
        if contract.get('has_audio'):
            audios = _audio_candidates(prepared, contract)
            if not audios:
                return None
            # Choose highest eligible quality; reuse muxed bytes only when it
            # satisfies that quality rather than silently selecting weaker audio.
            audio = audios[0]
            if video in audios and representation_rank(video) >= representation_rank(audio):
                audio = video
        return {'video': video, 'audio': None if audio is video else audio, 'muxed': audio is video}
    if contract.get('kind') in {'mp3', 'original_audio'}:
        audios = _audio_candidates(prepared, contract)
        return {'video': None, 'audio': audios[0], 'muxed': audios[0].get('kind') == 'muxed'} if audios else None
    return None


def _with_track_keys(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed = {s['source_index']: (t['track_key'], t['role']) for t in audio_tracks(streams) for s in t['representations']}
    return [{**s, **({'track_key': keyed[i][0], 'logical_role': keyed[i][1]} if i in keyed else {})} for i, s in enumerate(streams)]
