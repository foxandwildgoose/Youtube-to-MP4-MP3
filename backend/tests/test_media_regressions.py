"""B09–B13/B17/B18: synthetic metadata and actual FFmpeg artifact contracts.

Network-free fixtures do not establish successful YouTube downloads.
"""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.db import connect
from app.engine import child
from app.engine.ffmpeg_ops import build_command, run_ffmpeg
from app.errors import AppError
from app.services.format_planner import audio_tracks, plan_outputs
from app.services.match import resolve_contract
from app.services.media_validate import media_rotation, probe, validate_output


def video(**overrides):
    return {'kind': 'video', 'format_id': 'v30', 'vcodec': 'h264', 'acodec': 'none',
            'width': 1920, 'height': 1080, 'fps': 30, 'pix_fmt': 'yuv420p',
            'bit_depth': 8, 'dynamic_range': 'sdr', **overrides}


def audio(rate=256, **overrides):
    return {'kind': 'audio', 'format_id': f'a{rate}', 'vcodec': 'none', 'acodec': 'aac',
            'language': 'en', 'role': 'original', 'abr': rate, **overrides}


def choose(plan, kind='mp3'):
    return next(c for c in plan['choices'] if c['kind'] == kind and c.get('is_default'))


def tool_payload(settings):
    return {'ffmpeg': settings.ffmpeg_path, 'ffprobe': settings.ffprobe_path, 'deno': settings.deno_path}


def run_checked(command):
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]


def test_b09_track_identity_quality_and_language_survive_permutations(settings):
    streams = [audio(48), audio(256), audio(192, acodec='opus', format_id='opus'), audio(160, language='ko', format_id='ko')]
    keys = set()
    for permutation in itertools.permutations(streams):
        plan = plan_outputs(list(permutation), 10, settings)
        assert len(plan['audio_tracks']) == 2
        selected = choose(plan)
        keys.add(selected['audio_track_key'])
        assert selected['audio_language'] == 'en'
        assert selected['input_audio_min_kbps'] == 256
        matched = resolve_contract(list(reversed(permutation)), selected, settings.native_mp4_cap)
        assert matched['audio']['format_id'] == 'a256'
    assert len(keys) == 1
    contract = choose(plan_outputs(streams, 10, settings))
    assert resolve_contract([audio(48)], contract, settings.native_mp4_cap) is None
    assert resolve_contract([audio(256, language='ko')], contract, settings.native_mp4_cap) is None
    assert resolve_contract([audio(256, role='alternate')], contract, settings.native_mp4_cap) is None


def test_b09_distinct_provider_tracks_and_roles_and_codec_variants(settings):
    streams = [audio(48), audio(256), audio(160, role='default'), audio(160, role='alternate'),
               audio(160, audio_track_id='commentary', role='commentary'), audio(192, acodec='opus')]
    tracks = audio_tracks(streams)
    assert len(tracks) == 4
    original = next(t for t in tracks if t['role'] == 'original')
    assert len(original['representations']) == 3
    plan = plan_outputs(streams, 10, settings)
    assert len([c for c in plan['choices'] if c['kind'] == 'mp3']) == 12
    assert len([c for c in plan['choices'] if c['kind'] == 'original_audio']) == 5


def test_b10_distinct_rates_survive_and_unknown_cannot_satisfy_promised_rate(settings):
    streams = [video(), video(fps='60000/1001', format_id='v60'), audio()]
    choices = [c for c in plan_outputs(streams, 10, settings)['choices'] if c['kind'] == 'mp4' and not c['conversion']]
    assert len(choices) == 2
    high = max(choices, key=lambda c: c['output_fps'])
    assert high['is_default']
    assert resolve_contract([video(fps=None), audio()], high, settings.native_mp4_cap) is None
    assert resolve_contract([video(fps=24), audio()], high, settings.native_mp4_cap) is None


def test_b12_sanitize_provenance_and_no_durable_signed_urls(settings):
    metadata = {'id': 'fixH264aacA', 'duration': 1, 'title': 'test', 'formats': [
        {**video(kind='muxed', acodec='aac'), 'url': 'https://cdn.invalid/private?token=secret', 'filesize_approx': 1000}]}
    info = child.sanitize_info(metadata, metadata['id'])
    assert info['streams'][0]['filesize'] is None
    assert info['streams'][0]['filesize_approx'] == 1000
    assert 'secret' not in json.dumps(info)
    contract = choose(plan_outputs(info['streams'], 1, settings), 'mp4')
    assert contract['input_bytes'] == 1000
    assert contract['input_size_provenance'] == 'approximate'
    assert contract['size_is_estimate'] is True
    assert contract['size_estimate'] == contract['estimated_output_bytes']
    assert contract['output_size_provenance'] == 'approximate'
    assert contract['expected_workspace_bytes'] == 1000 + contract['estimated_output_bytes']
    assert 'secret' not in json.dumps(contract)


@pytest.mark.parametrize('provenance', ['exact', 'approximate', 'unknown'])
def test_b12_separate_inputs_and_unknown_size(settings, provenance):
    values = {'filesize': 1000} if provenance == 'exact' else ({'filesize_approx': 1000} if provenance == 'approximate' else {})
    streams = [video(**values), audio(filesize=200)]
    contract = choose(plan_outputs(streams, 10, settings), 'mp4')
    assert contract['input_bytes'] == (1200 if provenance != 'unknown' else None)
    assert contract['input_size_provenance'] == provenance
    assert contract['size_is_estimate'] is True
    if provenance == 'unknown':
        assert contract['estimated_output_bytes'] is None
        assert contract['expected_workspace_bytes'] is None


@pytest.mark.parametrize('rate', [128, 192, 320])
def test_b13_saved_mp3_preference_authoritative_future_analysis(api, settings, rate):
    api.ready()
    response = api.client.patch('/api/v1/settings', json={'mp3_bitrate': rate}, headers=api.headers())
    assert response.status_code == 200, response.text
    analysis = api.analyze()
    assert analysis['effective_mp3_bitrate'] == rate
    selected = next(c for c in analysis['choices'] if c['kind'] == 'mp3' and c['is_default'])
    assert selected['bitrate_kbps'] == rate
    created = api.create(analysis, choice_id=selected['choice_id'], key=f'preference-{rate}-queued')
    assert created.status_code == 202, created.text
    job_id = created.json()['id']
    # Analysis reads persisted settings on every call, as after API restart.
    conn = connect(settings)
    try:
        saved = json.loads(conn.execute('SELECT choices_json FROM analyses WHERE id=?', (analysis['analysis_id'],)).fetchone()[0])
        original = next(c['contract'] for c in saved if c['choice_id'] == selected['choice_id'])
        conn.execute('UPDATE preferences SET mp3_bitrate=? WHERE id=1', (128 if rate != 128 else 320,))
        queued = json.loads(conn.execute('SELECT contract_json FROM jobs WHERE id=?', (job_id,)).fetchone()[0])
        assert queued['mp3_bitrate'] == rate
    finally:
        conn.close()
    assert original['mp3_bitrate'] == rate
    assert api.analyze()['effective_mp3_bitrate'] != rate


def test_b13_missing_preference_and_no_audio(settings):
    planned = plan_outputs([video()], 1, settings, mp3_default_kbps=None)
    assert planned['effective_mp3_bitrate'] == settings.mp3_default_kbps
    assert not any(c['kind'] == 'mp3' for c in planned['choices'])


def test_b10_actual_24fps_rejects_promised_60_and_truncation(settings, media_root):
    path = media_root / 'small.mp4'
    streams = child.streams_from_file(path, tool_payload(settings))
    contract = choose(plan_outputs(streams, 1, settings), 'mp4')
    facts = validate_output(settings, path, contract)
    assert facts['bytes'] == path.stat().st_size
    assert probe(settings, path)['streams'][0]['avg_frame_rate'] == '24/1'
    with pytest.raises(AppError, match='OUTPUT_INVALID'):
        validate_output(settings, path, {**contract, 'output_fps': 60})
    with pytest.raises(AppError, match='OUTPUT_INVALID'):
        validate_output(settings, path, {**contract, 'duration': 10})
    with pytest.raises(AppError):
        validate_output(settings, path, {**contract, 'duration': 3600})


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_b11_real_rotation_copy_and_conversion(settings, media_root, tmp_path, rotation):
    rotated = tmp_path / f'rotation-{rotation}.mp4'
    run_checked([settings.ffmpeg_path, '-y', '-i', str(media_root / 'h264.mp4'), '-c', 'copy', '-metadata:s:v:0', f'rotate={rotation}', str(rotated)])
    source = probe(settings, rotated)
    # FFmpeg 7 moved matrix overrides from rotate metadata to an input option;
    # FFmpeg 5 (supported Debian image) still accepts rotate metadata.
    if media_rotation(next(s for s in source['streams'] if s['codec_type'] == 'video')) != rotation:
        run_checked([settings.ffmpeg_path, '-y', '-display_rotation', str(rotation), '-i', str(media_root / 'h264.mp4'), '-c', 'copy', str(rotated)])
        source = probe(settings, rotated)
    measured = media_rotation(next(s for s in source['streams'] if s['codec_type'] == 'video'))
    assert measured == rotation
    streams = child.streams_from_file(rotated, tool_payload(settings))
    plans = plan_outputs(streams, 1, replace(settings, conversion_cap=90), transcoding_enabled=True)
    native = next(c for c in plans['choices'] if c['kind'] == 'mp4' and not c['conversion'])
    assert (native['input_width'], native['input_height']) == (320, 180)
    assert (native['output_width'], native['output_height']) == ((180, 320) if rotation in {90, 270} else (320, 180))
    assert resolve_contract(streams, native, settings.native_mp4_cap)
    for contract in [native, next(c for c in plans['choices'] if c['kind'] == 'mp4' and c['conversion'])]:
        output = tmp_path / f"{rotation}-{'encode' if contract['conversion'] else 'copy'}.mp4"
        cmd = build_command(settings, contract, [rotated], output, tmp_path / 'progress')
        run_checked(cmd)
        validate_output(settings, output, contract)
        actual_streams = probe(settings, output)['streams']
        assert next(s for s in actual_streams if s['codec_type'] == 'audio')['tags']['language'] == 'kor'
        actual = next(s for s in actual_streams if s['codec_type'] == 'video')
        assert media_rotation(actual) == (0 if contract['conversion'] else rotation)
        assert actual['width'] <= 320 and actual['height'] <= 320
        # Decode display-oriented pixels independently: dimensions/matrix alone
        # would miss a physically double-rotated or stretched conversion.
        def display_pixels(path):
            decoded = subprocess.run([settings.ffmpeg_path, '-v', 'error', '-i', str(path), '-frames:v', '1',
                                      '-vf', 'scale=64:64', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'], capture_output=True)
            assert decoded.returncode == 0
            return decoded.stdout
        reference, result = display_pixels(rotated), display_pixels(output)
        assert len(reference) == len(result) == 64 * 64 * 3
        assert sum(abs(a - b) for a, b in zip(reference, result)) / len(reference) < 15


def test_b10_actual_rational_and_variable_average_rate(settings, tmp_path):
    for name, filters in [('rational', []), ('variable', ['-vf', "setpts='if(lt(N,15),N/(30*TB),(N-15)/(15*TB)+0.5/TB)'", '-fps_mode', 'vfr'])]:
        path = tmp_path / f'{name}.mp4'
        run_checked([settings.ffmpeg_path, '-y', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=30000/1001:duration=1',
                     *filters, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)])
        streams = child.streams_from_file(path, tool_payload(settings))
        actual = probe(settings, path)
        duration = float(actual['format']['duration'])
        contract = choose(plan_outputs(streams, duration, settings), 'mp4')
        assert contract['output_fps'] > 0
        validate_output(settings, path, contract)
        if name == 'rational':
            assert actual['streams'][0]['avg_frame_rate'] == '30000/1001'
        else:
            assert actual['streams'][0]['avg_frame_rate'] != actual['streams'][0]['r_frame_rate']


@pytest.mark.parametrize('speed,expected', [('0.5x', 100), ('2.0x', 25), ('N/A', None), ('nanx', None), ('0x', None)])
def test_b18_eta_is_measured_wall_clock(monkeypatch, speed, expected):
    events = []
    monkeypatch.setattr(child, 'emit', events.append)
    child._emit_ffmpeg_values({'out_time_us': '50000000', 'speed': speed}, 100, 'transcoding')
    assert events[-1]['eta_seconds'] == expected
    assert events[-1]['percent'] == 50
    assert events[-1]['component'] == 'output'
    assert events[-1]['downloaded_bytes'] is None


def test_b18_incremental_progress_and_bounded_stderr(settings, tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(child, 'emit', events.append)
    monkeypatch.setattr('app.config.load_settings', lambda: replace(settings, log_max_bytes=4096))
    progress = tmp_path / 'ffmpeg.progress'
    script = "import sys;sys.stderr.write('x'*2000000);sys.stdout.write('out_time_us=50000000\\nspeed=2.0x\\nprogress=end\\n')"
    code = child._run_ffmpeg([sys.executable, '-c', script, '-progress', str(progress)], progress, 100, 10, 'transcoding')
    assert code == 0
    assert progress.with_suffix('.err').stat().st_size == 4096
    assert not progress.exists()
    assert events[-1]['eta_seconds'] == 25


def test_b17_direct_selected_download_never_extracts_again(settings, tmp_path, monkeypatch):
    import yt_dlp
    calls = []
    target = tmp_path / 'a256.m4a'
    class SelectedOnly:
        def __init__(self, opts):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            pytest.fail('Redundant metadata extraction outside the bounded permit')
        def download(self, *args):
            pytest.fail('URL download would repeat metadata extraction')
        def prepare_filename(self, info):
            return str(target)
        def process_info(self, info):
            calls.append(info['format_id'])
            target.write_bytes(b'fixture-selected-input')
            self.opts['progress_hooks'][0]({'status': 'downloading', 'total_bytes': 20, 'downloaded_bytes': 10})
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', SelectedOnly)
    events = []
    monkeypatch.setattr(child, 'emit', events.append)
    path = child._download_one(tool_payload(settings), tmp_path, {**audio(), '_download_info': {'id': 'fixH264aacA', 'format_id': 'a256'}}, 2, 2)
    assert path == target
    assert calls == ['a256']
    assert events[-1]['component'] == 'audio'
    assert events[-1]['component_index'] == 2
    assert events[-1]['component_count'] == 2


def test_b17_slow_metadata_deadline_cannot_outlive_permit(api, settings, monkeypatch):
    import time
    api.ready()
    monkeypatch.setattr('app.config.load_settings', lambda: settings)
    started = time.monotonic()
    with pytest.raises(SystemExit):
        child._with_slot({'manage_slot': True, 'analysis_deadline_seconds': 1}, lambda: time.sleep(3))
    assert time.monotonic() - started < 2
    conn = connect(settings)
    try:
        assert conn.execute('SELECT count(*) FROM analysis_slots').fetchone()[0] == 0
    finally:
        conn.close()


def test_b17_cooldown_blocks_new_metadata_before_provider_call(api, settings, monkeypatch):
    from app.services.analysis import set_cooldown
    api.ready()
    conn = connect(settings)
    try:
        set_cooldown(conn, 60, 'fixture')
    finally:
        conn.close()
    monkeypatch.setattr('app.config.load_settings', lambda: settings)
    with pytest.raises(AppError) as caught:
        child._with_slot({'manage_slot': True}, lambda: pytest.fail('Provider must not be called during cooldown'))
    assert caught.value.code == 'SOURCE_RATE_LIMITED'


def test_b17_actual_ytdlp_selected_format_download_uses_fresh_info(settings, media_root, tmp_path):
    """Exercise real yt-dlp download processing against an owned local fixture."""
    import functools
    import http.server
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(media_root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        info = {'id': 'fixture-source', 'title': 'Owned generated fixture', 'format_id': 'selected',
                'ext': 'mp4', 'protocol': 'http', 'vcodec': 'h264', 'acodec': 'aac',
                'url': f'http://127.0.0.1:{server.server_port}/h264.mp4'}
        target = child._download_one(tool_payload(settings), tmp_path, {'kind': 'muxed', 'format_id': 'selected', '_download_info': info})
        assert target.read_bytes() == (media_root / 'h264.mp4').read_bytes()
        assert probe(settings, target)['streams'][0]['codec_name'] == 'h264'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_b17_retry_after_and_global_cooldown_never_shorten(api, settings):
    import urllib.error
    from app.services.analysis import _cooldown_seconds, set_cooldown
    provider_error = urllib.error.HTTPError('https://fixture.invalid', 429, 'rate limited', {'Retry-After': '120'}, None)
    wrapped = RuntimeError('provider error 429')
    wrapped.__cause__ = provider_error
    assert child._retry_after(wrapped) == 120
    assert child._retry_after(RuntimeError('429 Retry-After: 30')) == 30
    assert child._retry_after(RuntimeError('429 retry this video 256')) is None
    api.ready()
    conn = connect(settings)
    try:
        set_cooldown(conn, 120, 'fixture')
        set_cooldown(conn, 10, 'shorter fixture')
        assert _cooldown_seconds(conn) >= 119
    finally:
        conn.close()


@pytest.mark.parametrize('duration', [None, 'N/A', 'nan', '0', 'broken'])
def test_b10_unknown_or_malformed_probe_duration_cannot_publish(settings, media_root, monkeypatch, duration):
    from app.services import media_validate
    path = media_root / 'small.mp4'
    streams = child.streams_from_file(path, tool_payload(settings))
    contract = choose(plan_outputs(streams, 1, settings), 'mp4')
    malformed = probe(settings, path)
    malformed['format']['duration'] = duration
    monkeypatch.setattr(media_validate, 'probe', lambda *args: malformed)
    with pytest.raises(AppError) as caught:
        validate_output(settings, path, contract)
    assert caught.value.code == 'OUTPUT_INVALID'


def test_b17_held_metadata_slot_fails_retryably(api, settings, monkeypatch):
    from app.services.slots import acquire_slot, release_slot
    api.ready()
    slot = acquire_slot(settings, 'held-by-analysis-fixture')
    assert slot
    events = []
    monkeypatch.setattr('app.config.load_settings', lambda: settings)
    monkeypatch.setattr(child, 'emit', events.append)
    try:
        with pytest.raises(SystemExit):
            child._with_slot({'manage_slot': True, 'analysis_deadline_seconds': 1}, lambda: pytest.fail('Held permit must prevent metadata work'))
        assert events[-1]['code'] == 'ENGINE_ERROR'
        assert events[-1]['retryable'] is True
    finally:
        release_slot(settings, slot)


def test_b10_owned_child_returns_checked_facts_and_verifying_phase(settings, media_root, tmp_path, monkeypatch):
    path = media_root / 'h264.mp4'
    streams = child.streams_from_file(path, tool_payload(settings))
    contract = choose(plan_outputs(streams, 1, settings), 'mp4')
    events = []
    monkeypatch.setattr('app.config.load_settings', lambda: settings)
    monkeypatch.setattr(child, 'emit', events.append)
    output = tmp_path / 'final.mp4'
    checked = child._ffmpeg_finish({**tool_payload(settings), 'contract': contract, 'work_dir': str(tmp_path), 'output_path': str(output)}, [path])
    assert checked['bytes'] == output.stat().st_size
    assert checked['video']['codec'] == 'h264'
    assert checked['audio']['codec'] == 'aac'
    assert any(event.get('phase') == 'verifying' and event['percent'] is None for event in events)
