"""Owned-process, silent-work budget, persistent retry and long-worker gates."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app import engine_runner, worker
from app.config import validate_limits
from app.db import connect, init_db, utc_iso, utc_now
from app.errors import AppError
from app.services.analysis import set_cooldown
from app.services.storage import directory_size, job_workspace


def _fake_engine(monkeypatch, script: str) -> None:
    real_popen = subprocess.Popen

    def launch(_command, **kwargs):
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(engine_runner.subprocess, "Popen", launch)


def _alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


@pytest.mark.parametrize("failure", [RuntimeError("callback failed"), sqlite3.OperationalError("database unavailable")])
def test_callback_failure_stops_and_reaps_leader_and_descendant(settings, monkeypatch, failure):
    init_db(settings).close()
    script = '''
import json, subprocess, sys, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
print(json.dumps({"type":"progress", "phase":"encoding", "pids":[__import__('os').getpid(), child.pid]}), flush=True)
time.sleep(60)
'''
    _fake_engine(monkeypatch, script)
    pids = []

    def fail(event):
        pids.extend(event["pids"])
        raise failure

    started = time.monotonic()
    with pytest.raises(type(failure)):
        engine_runner.execute({}, settings, on_event=fail, deadline_seconds=10)
    assert time.monotonic() - started < 7
    assert len(pids) == 2
    assert all(not _alive(pid) for pid in pids)
    assert not list(settings.db_path.parent.glob("engine-*.json"))


def test_success_still_stops_inherited_pipe_descendant(settings, monkeypatch):
    init_db(settings).close()
    pids_path = settings.data_dir / "descendant.pid"
    script = f'''
import subprocess,sys,json
child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])
open({str(pids_path)!r},"w").write(str(child.pid))
print(json.dumps({{"type":"result","ok":True}}),flush=True)
'''
    _fake_engine(monkeypatch, script)
    result = engine_runner.execute({}, settings, deadline_seconds=5)
    assert result["status"] == "ok"
    assert not _alive(int(pids_path.read_text()))


@pytest.mark.parametrize("budget", ["input", "output", "workspace", "managed", "free"])
def test_silent_growing_engine_is_stopped_by_actual_budget(settings, monkeypatch, budget):
    init_db(settings).close()
    work = settings.tmp_dir / "owned-synthetic"
    work.mkdir()
    output = work / "final.mp4"
    kept = settings.files_dir / "kept.bin"
    kept.write_bytes(b"keep")
    cfg = settings
    if budget == "input":
        cfg = replace(settings, max_input_bytes=128)
    elif budget == "output":
        cfg = replace(settings, max_output_bytes=128)
    elif budget == "workspace":
        cfg = replace(settings, max_workspace_bytes=1536)
    elif budget == "managed":
        cfg = replace(settings, max_storage_bytes=directory_size(settings.data_dir) + 1024)
    else:
        cfg = replace(settings, min_free_bytes=1)
        monkeypatch.setattr(worker, "free_bytes", lambda _: 0)
    target = output if budget == "output" else work / "input.bin"
    script = f'''
import time,os
open({str(target)!r},"wb").write(b"x"*4096)
time.sleep(60)
'''
    _fake_engine(monkeypatch, script)
    started = time.monotonic()
    result = engine_runner.execute({}, cfg, watchdog=lambda: worker._runtime_budgets(cfg, work, output), deadline_seconds=10)
    assert result["status"] == "error"
    assert result["error"]["code"] == ("STORAGE_FULL" if budget in {"managed", "free"} else "LIMIT_EXCEEDED")
    assert time.monotonic() - started < 4
    assert kept.read_bytes() == b"keep"


@pytest.mark.parametrize("budget", ["input", "output", "workspace"])
def test_fixture_limit_failure_never_publishes_and_releases_reservation(api, settings, budget):
    api.ready()
    analysis = api.analyze()
    job_id = api.create(analysis, key=f"runtime-budget-{budget}").json()["id"]
    assert worker.claim_next(settings, "test") == job_id
    cfg = replace(settings, **{f"max_{budget}_bytes": 128})
    worker.process_job(cfg, job_id)
    conn = connect(settings)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == "failed"
        assert json.loads(row["error_json"])["code"] == "LIMIT_EXCEEDED"
        assert row["file_state"] == "none"
        assert not conn.execute("SELECT 1 FROM storage_reservations WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    assert not job_workspace(settings, job_id).exists()
    assert not (settings.files_dir / job_id).exists()


def test_missing_authoritative_row_stops_work(settings):
    init_db(settings).close()
    assert worker._cancelled(settings, "missing") is True


def test_cooldown_blocks_claim_and_shared_metadata_slot(api, settings):
    from app.services.slots import acquire_slot

    api.ready()
    job_id = api.create(api.analyze(), key="cooldown-claim").json()["id"]
    conn = connect(settings)
    try:
        set_cooldown(conn, 120, "synthetic 429")
    finally:
        conn.close()
    assert worker.claim_next(settings, "test") is None
    with pytest.raises(AppError) as caught:
        acquire_slot(settings, "test-probe")
    assert caught.value.code == "SOURCE_RATE_LIMITED"
    assert caught.value.retry_after >= 119
    conn = connect(settings)
    try:
        assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"] == "queued"
        assert conn.execute("SELECT COUNT(*) c FROM analysis_slots").fetchone()["c"] == 0
    finally:
        conn.close()


def test_retry_wait_survives_restart_and_finite_budget(api, settings, monkeypatch):
    api.ready()
    job_id = api.create(api.analyze(), key="retry-persist").json()["id"]
    monkeypatch.setattr(worker, "execute", lambda *a, **kw: {"status": "error", "error": {"code": "ENGINE_ERROR", "retryable": True}})
    for attempt in range(settings.max_auto_retries + 1):
        assert worker.claim_next(settings, "test") == job_id
        worker.process_job(settings, job_id)
        conn = connect(settings)
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row["attempts_used"] == attempt + 1
            if attempt < settings.max_auto_retries:
                assert row["status"] == "queued" and row["phase"] == "retry_wait"
                assert row["next_attempt_at"] > utc_iso()
                assert worker.reconcile_abandoned(settings) == 0
                assert worker.claim_next(settings, "restarted") is None
                conn.execute("UPDATE jobs SET next_attempt_at = ? WHERE id = ?", (utc_iso(utc_now() - timedelta(seconds=1)), job_id))
            else:
                assert row["status"] == "failed"
                assert not conn.execute("SELECT 1 FROM storage_reservations WHERE job_id = ?", (job_id,)).fetchone()
        finally:
            conn.close()


def test_busy_worker_heartbeat_and_housekeeping_beyond_stale_threshold(api, settings, monkeypatch):
    """Advance 36 seconds with a controlled UTC clock while job emits no events."""
    import app.db as db
    import app.diagnostics as diagnostics

    api.ready()
    job_id = api.create(api.analyze(), key="long-job-clock").json()["id"]
    base = utc_now()
    clock = [base]
    for module in (worker, db, diagnostics):
        monkeypatch.setattr(module, "utc_now", lambda: clock[0])
    monkeypatch.setattr(worker, "CONTROL_INTERVAL_SECONDS", 0.005)
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_SECONDS", 0.005)
    monkeypatch.setattr(worker, "HOUSEKEEPING_INTERVAL_SECONDS", 0.005)
    monkeypatch.setattr(diagnostics, "_tool_summary", lambda _: {"encoders": {"libx264": True, "aac": True, "libmp3lame": True}, "yt_dlp": "fixture", "yt_dlp_ejs": "fixture", "deno": "fixture", "ffmpeg": "fixture", "ffprobe": "fixture"})
    started = threading.Event()
    stop = threading.Event()
    housekeeping = []
    real_expire = worker.expire_finished_files

    def expire(conn, cfg):
        housekeeping.append(clock[0])
        return real_expire(conn, cfg)

    def silent_job(cfg, identity, stopping):
        assert identity == job_id
        started.set()
        stopping.wait(10)
        worker._fail(cfg, identity, "INTERRUPTED", retryable=True)

    monkeypatch.setattr(worker, "expire_finished_files", expire)
    monkeypatch.setattr(worker, "process_job", silent_job)
    thread = threading.Thread(target=worker.serve_forever, args=(settings, stop))
    thread.start()
    try:
        assert started.wait(3)
        for seconds in range(1, 37):
            clock[0] = base + timedelta(seconds=seconds)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                conn = connect(settings)
                try:
                    state = diagnostics.diagnostics(settings, conn)
                finally:
                    conn.close()
                if state["worker"]["age_seconds"] == 0:
                    break
                time.sleep(0.005)
            assert state["worker"]["stale"] is False
            assert state["ready"] is True
        assert max(housekeeping) >= base + timedelta(seconds=35)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    clock[0] += timedelta(seconds=31)
    conn = connect(settings)
    try:
        assert diagnostics.diagnostics(settings, conn)["worker"]["stale"] is True
    finally:
        conn.close()


@pytest.mark.parametrize("changes", [
    {"media_concurrency": 2}, {"media_concurrency": 0}, {"analysis_concurrency": 0},
    {"max_input_bytes": 0}, {"max_output_bytes": -1}, {"max_workspace_bytes": 0},
    {"history_retention_seconds": 0}, {"session_ttl_seconds": 0}, {"log_max_bytes": 0},
    {"max_source_duration_seconds": 0}, {"native_mp4_cap": 0},
    {"sse_heartbeat_seconds": float("nan")}, {"sse_heartbeat_seconds": float("inf")},
    {"max_auto_retries": 11},
])
def test_invalid_limits_rejected_clearly(settings, changes):
    with pytest.raises(SystemExit, match="Unsupported configuration"):
        validate_limits(replace(settings, **changes))


def test_tool_diagnostics_are_cached_but_worker_readiness_is_live(settings, monkeypatch):
    import app.diagnostics as diagnostics

    init_db(settings).close()
    diagnostics._TOOLS_CACHE.clear()
    calls = []
    monkeypatch.setattr(diagnostics, "_first_line", lambda cmd: calls.append(cmd) or "tool fixture")
    monkeypatch.setattr(diagnostics, "_encoders", lambda _: {"libx264": True, "aac": True, "libmp3lame": True})
    conn = connect(settings)
    try:
        first = diagnostics.diagnostics(settings, conn)
        worker.beat(settings, "test")
        second = diagnostics.diagnostics(settings, conn)
    finally:
        conn.close()
    assert len(calls) == 3
    assert first["worker"] is None
    assert second["worker"]["stale"] is False


def test_cancel_stops_actual_ffmpeg_group(settings, monkeypatch):
    init_db(settings).close()
    artifact = settings.tmp_dir / "cancelled.wav"
    pids_file = settings.data_dir / "ffmpeg-pids.json"
    script = f'''
import subprocess,time,json,os
child=subprocess.Popen([{settings.ffmpeg_path!r},"-nostdin","-v","error","-re","-f","lavfi","-i","sine=duration=60","-y",{str(artifact)!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open({str(pids_file)!r},"w").write(json.dumps([os.getpid(),child.pid]))
print(json.dumps({{"type":"progress","phase":"encoding"}}),flush=True)
child.wait()
'''
    _fake_engine(monkeypatch, script)
    started = time.monotonic()
    outcome = engine_runner.execute({}, settings, should_cancel=lambda: time.monotonic() - started > 0.5, deadline_seconds=5)
    assert outcome["status"] == "cancelled"
    assert all(not _alive(pid) for pid in json.loads(pids_file.read_text()))
    assert not list(settings.db_path.parent.glob("engine-*.json"))


def test_sigterm_worker_interrupts_real_owned_engine(api, settings):
    api.ready()
    catalog = json.loads(settings.fixture_catalog.read_text())
    catalog["fixSleepAAA"]["sleep_seconds"] = 60
    settings.fixture_catalog.write_text(json.dumps(catalog))
    job_id = api.create(api.analyze("fixSleepAAA"), key="sigterm-real-job").json()["id"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    process = subprocess.Popen([sys.executable, "-m", "app.worker"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    engine_pid = None
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            markers = list(settings.db_path.parent.glob("engine-*.json"))
            if markers:
                engine_pid = json.loads(markers[0].read_text())["pid"]
                break
            time.sleep(0.02)
        assert engine_pid is not None
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=8) == 0
        assert not _alive(engine_pid)
        conn = connect(settings)
        try:
            row = conn.execute("SELECT status, error_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row["status"] == "interrupted"
            assert json.loads(row["error_json"])["code"] == "INTERRUPTED"
            assert not conn.execute("SELECT 1 FROM storage_reservations WHERE job_id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
        assert not job_workspace(settings, job_id).exists()
        assert not (settings.files_dir / job_id).exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if engine_pid and _alive(engine_pid):
            try:
                os.killpg(engine_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_restart_cleans_dead_owner_group_but_preserves_live_api_owner(settings):
    init_db(settings).close()
    engine_runner._enable_subreaper()
    processes = []
    try:
        for live in (False, True):
            process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True)
            processes.append(process)
            marker = engine_runner._record_engine(settings, process)
            if not live:
                info = json.loads(marker.read_text())
                info["owner_pid"] = 99999999
                marker.write_text(json.dumps(info))
        engine_runner.cleanup_stale_engines(settings)
        processes[0].wait(timeout=4)
        assert not _alive(processes[0].pid)
        assert processes[1].poll() is None
        assert engine_runner._marker_path(settings, processes[1].pid).exists()
    finally:
        for process in processes:
            engine_runner._terminate(process)
            engine_runner._marker_path(settings, process.pid).unlink(missing_ok=True)


def test_worker_429_persists_cooldown_before_other_metadata_starts(api, settings, monkeypatch):
    import app.services.analysis as analysis_service

    api.ready()
    job_id = api.create(api.analyze(), key="worker-real-429").json()["id"]
    calls = []
    monkeypatch.setattr(worker, "execute", lambda *a, **kw: calls.append("download") or {"status": "error", "error": {"code": "SOURCE_RATE_LIMITED", "retry_after": 7}})
    assert worker.claim_next(settings, "first") == job_id
    worker.process_job(settings, job_id)
    monkeypatch.setattr(analysis_service, "execute", lambda *a, **kw: calls.append("metadata"))
    response = api.client.post("/api/v1/analyses", json={"url": "https://www.youtube.com/watch?v=fixH264aacA"}, headers=api.headers())
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 6
    assert worker.reconcile_abandoned(settings) == 0
    assert worker.claim_next(settings, "restarted") is None
    assert calls == ["download"]
    conn = connect(settings)
    try:
        row = conn.execute("SELECT status, phase, next_attempt_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == "queued" and row["phase"] == "retry_wait"
        assert row["next_attempt_at"] > utc_iso()
    finally:
        conn.close()


def test_403_refresh_is_finite_and_auth_policy_errors_are_terminal(api, settings, monkeypatch):
    api.ready()
    analysis = api.analyze()
    for code in ("HTTP_403", "SOURCE_AUTH_REQUIRED", "SOURCE_FORBIDDEN"):
        job_id = api.create(analysis, key=f"finite-policy-{code}").json()["id"]
        monkeypatch.setattr(worker, "execute", lambda *a, code=code, **kw: {"status": "error", "error": {"code": code, "retryable": True}})
        assert worker.claim_next(settings, "test") == job_id
        worker.process_job(settings, job_id)
        if code == "HTTP_403":
            assert worker.reconcile_abandoned(settings) == 0
            conn = connect(settings)
            try:
                conn.execute("UPDATE jobs SET next_attempt_at = ? WHERE id = ?", (utc_iso(utc_now() - timedelta(seconds=1)), job_id))
            finally:
                conn.close()
            assert worker.claim_next(settings, "restarted") == job_id
            worker.process_job(settings, job_id)
        conn = connect(settings)
        try:
            row = conn.execute("SELECT status,error_json,attempts_used FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row["status"] == "failed"
            assert json.loads(row["error_json"])["code"] == ("SOURCE_FORBIDDEN" if code == "HTTP_403" else code)
            assert row["attempts_used"] == (2 if code == "HTTP_403" else 1)
        finally:
            conn.close()


def test_two_input_budget_and_shared_input_inode_accounting(settings):
    init_db(settings).close()
    work = settings.tmp_dir / "two-inputs"
    work.mkdir()
    output = work / "final.mp4"
    video, audio = work / "video.mp4", work / "audio.m4a"
    video.write_bytes(b"v" * 80)
    audio.write_bytes(b"a" * 80)
    cfg = replace(settings, max_input_bytes=128)
    with pytest.raises(AppError, match="LIMIT_EXCEEDED"):
        worker._runtime_budgets(cfg, work, output)
    audio.unlink()
    os.link(video, audio)
    worker._runtime_budgets(cfg, work, output)


def test_actual_silent_ffmpeg_output_growth_hits_output_budget(settings, monkeypatch):
    init_db(settings).close()
    work = settings.tmp_dir / "actual-growing-output"
    work.mkdir()
    output = work / "final.wav"
    pids_path = settings.data_dir / "growing-pids.json"
    script = f'''
import subprocess,json,os
child=subprocess.Popen([{settings.ffmpeg_path!r},"-nostdin","-v","error","-re","-f","lavfi","-i","sine=duration=60","-flush_packets","1","-y",{str(output)!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open({str(pids_path)!r},"w").write(json.dumps([os.getpid(),child.pid]))
child.wait()
'''
    _fake_engine(monkeypatch, script)
    cfg = replace(settings, max_output_bytes=4096)
    outcome = engine_runner.execute({}, cfg, watchdog=lambda: worker._runtime_budgets(cfg, work, output), deadline_seconds=10)
    assert outcome["status"] == "error" and outcome["error"]["code"] == "LIMIT_EXCEEDED"
    assert output.stat().st_size > 4096
    assert all(not _alive(pid) for pid in json.loads(pids_path.read_text()))


def test_late_terminal_callbacks_preserve_successful_retained_file(api, settings):
    api.ready()
    job_id = api.create(api.analyze(), key="keep-late-failure", keep=True).json()["id"]
    assert worker.claim_next(settings, "test") == job_id
    worker.process_job(settings, job_id)
    before = api.client.get(f"/api/v1/jobs/{job_id}/file")
    assert before.status_code == 200
    worker._fail(settings, job_id, "ENGINE_ERROR", retryable=True)
    worker._finish_cancelled(settings, job_id)
    worker._publish_success(settings, job_id, settings.tmp_dir / "absent.mp4", {}, {}, {})
    after = api.client.get(f"/api/v1/jobs/{job_id}/file")
    assert after.status_code == 200 and after.content == before.content
    current = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert current["status"] == "succeeded" and current["file_state"] == "available" and current["keep_on_server"]


def test_fixture_dependency_readiness_does_not_claim_provider_runtime(settings, monkeypatch):
    import app.diagnostics as diagnostics

    init_db(settings).close()
    worker.beat(settings, "fixture-owner")
    monkeypatch.setattr(diagnostics, "_tool_summary", lambda _: {"ffmpeg": "real fixture encoder", "ffprobe": "real fixture probe", "deno": None, "yt_dlp": None, "yt_dlp_ejs": None, "encoders": {"libx264": True, "aac": True, "libmp3lame": True}})
    conn = connect(settings)
    try:
        fixture = diagnostics.diagnostics(settings, conn)
        provider = diagnostics.diagnostics(replace(settings, media_adapter="ytdlp"), conn)
    finally:
        conn.close()
    assert fixture["demo_data"] is True and fixture["dependencies_ready"] is True and fixture["ready"] is True
    assert fixture["tools"]["deno"] is None
    assert provider["demo_data"] is False and provider["dependencies_ready"] is False and provider["ready"] is False


def test_final_result_is_drained_after_leader_exit(settings, monkeypatch):
    from queue import Queue

    init_db(settings).close()
    _fake_engine(monkeypatch, 'import json; print(json.dumps({"type":"result","ok":True}),flush=True)')

    class DelayedResultQueue(Queue):
        def put(self, value, *args, **kwargs):
            if isinstance(value, bytes) and b'"result"' in value:
                time.sleep(0.5)
            return super().put(value, *args, **kwargs)

    monkeypatch.setattr(engine_runner, "Queue", DelayedResultQueue)
    result = engine_runner.execute({}, settings, deadline_seconds=5)
    assert result["status"] == "ok" and result["result"]["ok"] is True


def test_foreign_pid_namespace_marker_cannot_signal_local_group(settings, monkeypatch):
    init_db(settings).close()
    process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True)
    local_marker = engine_runner._record_engine(settings, process)
    foreign_marker = None
    try:
        with monkeypatch.context() as context:
            context.setattr(engine_runner, "_namespace_id", lambda: "pid:[foreign-container]")
            foreign_marker = engine_runner._record_engine(settings, process)
            data = json.loads(foreign_marker.read_text())
            data["owner_pid"] = 99999999
            foreign_marker.write_text(json.dumps(data))
        assert foreign_marker != local_marker
        engine_runner.cleanup_stale_engines(settings)
        assert process.poll() is None
        assert local_marker.exists() and foreign_marker.exists()
    finally:
        engine_runner._terminate(process)
        local_marker.unlink(missing_ok=True)
        if foreign_marker:
            foreign_marker.unlink(missing_ok=True)


def test_publication_uses_checked_facts_from_supervised_engine(api, settings, monkeypatch):
    api.ready()
    job_id = api.create(api.analyze(), key="owned-validation-facts").json()["id"]

    def unsafe_parent_probe(*args, **kwargs):
        raise AssertionError("Publication must not launch an unsupervised probe")

    monkeypatch.setattr(worker, "validate_output", unsafe_parent_probe, raising=False)
    assert worker.claim_next(settings, "test") == job_id
    worker.process_job(settings, job_id)
    job = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job
    assert job["artifact"]["media"]["video"]["codec"] == "h264"
    assert job["artifact"]["media"]["audio"]["codec"] == "aac"
