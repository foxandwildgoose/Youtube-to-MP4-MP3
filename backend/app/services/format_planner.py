"""Pure media planning; logical tracks and encoded/display geometry are separate.

Source preference: highest reported bitrate, then dedicated audio, sample rate,
channels and a stable representation identifier. Output encoding never restores
source detail. Provider URLs never belong in these durable contracts.
"""
from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from typing import Any

from app.config import Settings

MP3_RATES = (128, 192, 320)


def norm_vcodec(value: str | None) -> str | None:
    if not value or value == "none":
        return None
    token = value.lower().split(" ")[0]
    for prefixes, codec in ((('avc1', 'h264'), 'h264'), (('vp9', 'vp09'), 'vp9'), (('av01',), 'av1'), (('hev1', 'hvc1', 'hevc'), 'hevc')):
        if token.startswith(prefixes):
            return codec
    return token.split('.')[0]


def norm_acodec(value: str | None) -> str | None:
    if not value or value == "none":
        return None
    token = value.lower()
    for prefixes, codec in ((('mp4a', 'aac'), 'aac'), (('opus',), 'opus'), (('mp3',), 'mp3')):
        if token.startswith(prefixes):
            return codec
    return 'vorbis' if 'vorbis' in token else token.split('.')[0]


def frame_rate(value: Any) -> float | None:
    try:
        number = float(Fraction(str(value)))
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def norm_rotation(value: Any) -> int:
    try:
        rotation = float(value or 0) % 360
        rounded = round(rotation / 90) * 90 % 360
        return rounded if abs(rotation - rounded) < 0.1 or abs(rotation - rounded - 360) < 0.1 else -1
    except (TypeError, ValueError, OverflowError):
        return -1


def display_size(width: int, height: int, rotation: int = 0) -> tuple[int, int]:
    return (height, width) if rotation % 180 == 90 else (width, height)


def fits_cap(width: int, height: int, cap: int) -> bool:
    long_cap = {1080: 1920, 2160: 3840}.get(cap, int(round(cap * 16 / 9)))
    return width > 0 and height > 0 and min(width, height) <= cap and max(width, height) <= long_cap


def resolution_label(width: int, height: int) -> str:
    short = min(width, height)
    return f'{short}p' if short in {360, 480, 720, 1080, 1440, 2160} else f'{width}×{height}'


def is_hdr(stream: dict[str, Any]) -> bool:
    return (str(stream.get('dynamic_range') or '').lower() == 'hdr'
            or str(stream.get('color_transfer') or '').lower() in {'smpte2084', 'arib-std-b67'}
            or str(stream.get('color_primaries') or '').lower() == 'bt2020')


def is_compatible_video(stream: dict[str, Any]) -> bool:
    return (norm_vcodec(stream.get('vcodec')) == 'h264' and not is_hdr(stream)
            and stream.get('bit_depth') in (None, 8)
            and stream.get('pix_fmt') in {'yuv420p', 'yuvj420p'})


def norm_language(value: Any) -> str | None:
    if not value or str(value).lower() in {'und', 'unk'}:
        return None
    value = str(value).strip().lower().replace('_', '-')
    return {'kor': 'ko', 'eng': 'en', 'jpn': 'ja', 'zho': 'zh', 'spa': 'es', 'fra': 'fr', 'deu': 'de'}.get(value, value)


def _audio_role(stream: dict[str, Any], index: int = 0) -> str:
    explicit = str(stream.get('role') or '').lower()
    if explicit in {'original', 'default', 'alternate', 'description', 'commentary'}:
        return explicit
    note = ' '.join(str(stream.get(k) or '') for k in ('note', 'track_name', 'format_note')).lower()
    if stream.get('is_original') or 'original' in note:
        return 'original'
    if 'description' in note or 'descriptive' in note:
        return 'description'
    if 'commentary' in note:
        return 'commentary'
    return 'default' if stream.get('is_default') or not stream.get('language') else 'alternate'


def size_fact(stream: dict[str, Any]) -> tuple[int | None, str]:
    for key, provenance in (('filesize', 'exact'), ('filesize_approx', 'approximate')):
        value = stream.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
            return int(value), str(stream.get('size_provenance') or provenance)
    return None, 'unknown'


def representation_rank(stream: dict[str, Any]) -> tuple:
    return (float(stream.get('abr') or 0), stream.get('kind') == 'audio', float(stream.get('asr') or 0),
            int(stream.get('audio_channels') or 0), norm_acodec(stream.get('acodec')) or '',
            str(stream.get('format_id') or ''), str(stream.get('protocol') or ''))


def audio_tracks(streams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for index, stream in enumerate(streams):
        codec = norm_acodec(stream.get('acodec'))
        if stream.get('kind') == 'video' or not codec:
            continue
        language, role = norm_language(stream.get('language')), _audio_role(stream)
        # Provider track IDs distinguish two same-language/role tracks, but a
        # format ID (bitrate/protocol representation) deliberately does not.
        identity = [language, role, str(stream.get('audio_track_id') or stream.get('track_id') or '')]
        key = 'track-' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
        track = groups.setdefault(key, {'track_key': key, 'language': language, 'role': role, 'representations': []})
        track['representations'].append({**stream, 'source_index': index, 'acodec': codec, 'track_key': key})
    order = {'original': 0, 'default': 1, 'alternate': 2, 'description': 3, 'commentary': 4}
    result = sorted(groups.values(), key=lambda t: (order.get(t['role'], 9), t['language'] or '', t['track_key']))
    for track in result:
        track['representations'].sort(key=representation_rank, reverse=True)
        best = track['representations'][0]
        track.update({k: best.get(k) for k in ('source_index', 'acodec', 'filesize', 'filesize_approx', 'abr', 'ext', 'kind')})
    return result


def _track_source(track: dict[str, Any], codec: str | None = None) -> dict[str, Any] | None:
    eligible = [s for s in track['representations'] if codec is None or s['acodec'] == codec]
    if not eligible:
        return None
    return {**track, **max(eligible, key=representation_rank), 'language': track['language'], 'role': track['role']}


def _video_view(stream: dict[str, Any], index: int = 0) -> dict[str, Any] | None:
    width, height, rotation = int(stream.get('width') or 0), int(stream.get('height') or 0), norm_rotation(stream.get('rotation'))
    if stream.get('kind') == 'audio' or not norm_vcodec(stream.get('vcodec')) or width <= 0 or height <= 0 or rotation < 0:
        return None
    dw, dh = display_size(width, height, rotation)
    return {**stream, 'source_index': index, 'vcodec': norm_vcodec(stream.get('vcodec')), 'acodec': norm_acodec(stream.get('acodec')),
            'width': dw, 'height': dh, 'encoded_width': width, 'encoded_height': height, 'rotation': rotation,
            'fps': frame_rate(stream.get('fps')), 'compatible': is_compatible_video(stream), 'hdr': is_hdr(stream),
            'dynamic_range': str(stream.get('dynamic_range') or ('hdr' if is_hdr(stream) else 'unknown')).lower()}


def _input_size(video, track) -> tuple[int | None, str]:
    parts = {}
    for source in (video, track):
        if source is not None:
            parts[source.get('physical_input_key', source['source_index'])] = size_fact(source)
    if not parts or any(size is None for size, _ in parts.values()):
        return None, 'unknown'
    return sum(size for size, _ in parts.values()), ('exact' if all(p == 'exact' for _, p in parts.values()) else 'approximate')


def plan_outputs(streams: list[dict[str, Any]], duration: float | None, settings: Settings, *, transcoding_enabled: bool | None = None, mp3_default_kbps: int | None = None) -> dict[str, Any]:
    enabled = settings.enable_transcoding if transcoding_enabled is None else transcoding_enabled
    effective_rate = mp3_default_kbps if mp3_default_kbps in MP3_RATES else settings.mp3_default_kbps
    videos = [v for i, s in enumerate(streams) if (v := _video_view(s, i))]
    tracks = audio_tracks(streams)
    choices = []
    compatible = [v for v in videos if v['compatible'] and fits_cap(v['width'], v['height'], settings.native_mp4_cap)]
    compatible.sort(key=lambda v: (v['width'] * v['height'], v['fps'] or 0, float(v.get('tbr') or 0), str(v.get('format_id') or '')), reverse=True)
    seen = set()
    for video in compatible:
        audio_options = [source for t in tracks if (source := _track_source(t, 'aac'))] or ([None] if not tracks else [])
        for track in audio_options:
            key = (video['width'], video['height'], video['rotation'], video['fps'], track['track_key'] if track else None)
            if key in seen:
                continue
            seen.add(key)
            choices.append(_choice('mp4', video, track, duration, 'mp4', 'video/mp4', 'h264', 'aac' if track else None))
    defaults = [c for c in choices if fits_cap(c['output_width'], c['output_height'], settings.default_mp4_cap)]
    if defaults:
        # The deterministic first track is preferred, then largest/fastest real option.
        first_track = tracks[0]['track_key'] if tracks else None
        best = max(defaults, key=lambda c: (c['audio_track_key'] == first_track, c['output_width'] * c['output_height'], c['output_fps'] or 0))
        best['is_default'] = True
    if enabled:
        sdr = sorted([v for v in videos if not v['hdr'] and v['dynamic_range'] == 'sdr'], key=lambda v: (v['width'] * v['height'], v['fps'] or 0, str(v.get('format_id') or '')), reverse=True)
        if sdr:
            source = sdr[0]
            size = _fit_box(source['width'], source['height'], settings.conversion_cap)
            for track in [_track_source(t) for t in tracks] or [None]:
                if any(c['output_width'] == size[0] and c['output_height'] == size[1] and c['output_fps'] == source['fps'] and c['audio_track_key'] == (track['track_key'] if track else None) for c in choices):
                    continue
                choices.append(_choice('mp4', source, track, duration, 'mp4', 'video/mp4', 'h264', 'aac' if track else None, conversion=True, output_size=size))
    for index, logical in enumerate(tracks):
        track = _track_source(logical)
        for rate in MP3_RATES:
            choice = _choice('mp3', None, track, duration, 'mp3', 'audio/mpeg', None, 'mp3', rate=rate)
            choice['is_default'] = index == 0 and rate == effective_rate
            choices.append(choice)
        for codec in sorted({s['acodec'] for s in logical['representations']}):
            original = _original_container(codec)
            if original:
                container, mime = original
                choices.append(_choice('original_audio', None, _track_source(logical, codec), duration, container, mime, None, codec))
    return {'audio_tracks': [{'track_key': t['track_key'], 'language': t['language'], 'role': t['role'], 'codec': t['acodec'], 'codecs': sorted({s['acodec'] for s in t['representations']}), 'representation_count': len(t['representations'])} for t in tracks], 'choices': choices, 'effective_mp3_bitrate': effective_rate}


def _original_container(acodec: str) -> tuple[str, str] | None:
    return {'aac': ('m4a', 'audio/mp4'), 'opus': ('webm', 'audio/webm'), 'mp3': ('mp3', 'audio/mpeg'), 'vorbis': ('ogg', 'audio/ogg')}.get(acodec)


def _fit_box(width: int, height: int, cap: int) -> tuple[int, int]:
    long_cap = {1080: 1920, 2160: 3840}.get(cap, int(round(cap * 16 / 9)))
    scale = min(1.0, cap / min(width, height), long_cap / max(width, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def _choice(kind, video, track, duration, container, mime, vcodec, acodec, *, conversion=False, output_size=None, rate=None):
    ow, oh = output_size or ((video['width'], video['height']) if video else (None, None))
    input_bytes, provenance = _input_size(video, track)
    estimate = None
    if kind == 'mp3' and duration:
        estimate = int(duration * rate * 1000 / 8) + 2048
    elif kind == 'original_audio' and track and track.get('kind') == 'muxed':
        # Extracted audio is not the size of its containing video file.
        if duration and track.get('abr'):
            estimate = int(duration * float(track['abr']) * 1000 / 8 * 1.02) + 1024
    elif not conversion and input_bytes is not None:
        # Input bytes are not an exact final-container size.
        estimate = int(input_bytes * 1.02) + 1024
    return {
        'kind': kind, 'conversion': conversion, 'requires_consent': conversion, 'container': container, 'ext': container, 'mime': mime,
        'has_video': kind == 'mp4', 'has_audio': bool(track), 'output_width': ow, 'output_height': oh,
        'output_encoded_width': ow if conversion else (video['encoded_width'] if video else None),
        'output_encoded_height': oh if conversion else (video['encoded_height'] if video else None),
        'output_rotation': 0 if conversion else (video['rotation'] if video else 0),
        'output_fps': video['fps'] if video else None, 'output_vcodec': vcodec, 'output_acodec': acodec,
        'input_vcodec': video['vcodec'] if video else None, 'input_width': video['encoded_width'] if video else None,
        'input_height': video['encoded_height'] if video else None, 'input_display_width': video['width'] if video else None,
        'input_display_height': video['height'] if video else None, 'input_rotation': video['rotation'] if video else 0,
        'input_fps': video['fps'] if video else None, 'input_acodec': track['acodec'] if track else None,
        'input_audio_min_kbps': track.get('abr') if track else None, 'audio_track_key': track['track_key'] if track else None,
        'audio_language': track['language'] if track else None, 'audio_role': track['role'] if track else None,
        'mp3_bitrate': rate, 'duration': duration,
        'label': f'MP3 {rate} kbps' if kind == 'mp3' else (f'Original {acodec.upper()}' if kind == 'original_audio' else resolution_label(ow, oh)),
        'resolution_label': resolution_label(ow, oh) if ow and oh else None,
        'input_bytes': input_bytes, 'input_size_provenance': provenance,
        'size_estimate': estimate, 'size_is_estimate': True, 'estimated_output_bytes': estimate,
        'output_size_provenance': 'approximate' if estimate is not None else 'unknown',
        'expected_workspace_bytes': input_bytes + estimate if input_bytes is not None and estimate is not None else None,
        'portrait': bool(ow and oh and oh > ow), 'is_default': False,
        'input_dynamic_range': video['dynamic_range'] if video else None,
    }
