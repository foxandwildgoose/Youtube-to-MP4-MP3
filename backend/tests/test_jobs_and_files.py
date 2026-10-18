"""Durable jobs, cancellation, files, security, and failure mapping."""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app.config import load_settings
from app.db import connect, utc_iso, utc_now
from app.services.safe_http import ip_blocked
from app.worker import claim_next, process_job, reconcile_abandoned


def _choice(analysis, kind, **pred):
    for item in analysis["choices"]:
        if item["kind"] != kind:
            continue
        if all(item.get(key) == value for key, value in pred.items()):
            return item["choice_id"]
    raise AssertionError((kind, pred, analysis["choices"]))


def test_fixture_mp4_mp3_and_original(api, settings):
    api.ready()
    analysis = api.analyze("fixH264aacA")
    assert analysis["source"]["title"] == "Fixture H264"
    assert analysis["source"]["thumbnail_url"] is None
    mp4 = api.create(analysis, kind="mp4", key="mp4-key-0001")
    assert mp4.status_code == 202, mp4.text
    job_id = mp4.json()["id"]
    assert claim_next(settings, "test-worker") == job_id
    process_job(settings, job_id)
    done = api.client.get(f"/api/v1/jobs/{job_id}", headers=api.headers())
    body = done.json()
    assert body["status"] == "succeeded", body
    assert body["file_state"] == "available"
    fetched = api.client.get(f"/api/v1/jobs/{job_id}/file")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("video/mp4")
    assert "filename*=" in fetched.headers["content-disposition"]
    assert len(fetched.content) > 100

    audio = api.analyze("fixAudioAAA")
    mp3_id = _choice(audio, "mp3", bitrate_kbps=192)
    created = api.create(audio, choice_id=mp3_id, key="mp3-key-0001")
    assert created.status_code == 202
    mp3_job = created.json()["id"]
    assert claim_next(settings, "test-worker") == mp3_job
    process_job(settings, mp3_job)
    saved = api.client.get(f"/api/v1/jobs/{mp3_job}/file")
    assert saved.status_code == 200
    assert saved.headers["content-type"].startswith("audio/mpeg")

    original_id = _choice(audio, "original_audio")
    original = api.create(audio, choice_id=original_id, key="orig-key-001")
    orig_job = original.json()["id"]
    assert claim_next(settings, "test-worker") == orig_job
    process_job(settings, orig_job)
    orig = api.client.get(f"/api/v1/jobs/{orig_job}")
    assert orig.json()["status"] == "succeeded"
    downloaded = api.client.get(f"/api/v1/jobs/{orig_job}/file")
    assert downloaded.headers["content-type"].startswith("audio/mp4")


def test_portrait_and_vp9_transcode(api, settings, monkeypatch):
    api.ready()
    portrait = api.analyze("fixPort180A")
    created = api.create(portrait, kind="mp4", key="port-key-001")
    job_id = created.json()["id"]
    assert claim_next(settings, "w") == job_id
    process_job(settings, job_id)
    body = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "succeeded", body
    vp9 = api.analyze("fixVP9opusA")
    assert not any(item["kind"] == "mp4" for item in vp9["choices"])
    monkeypatch.setenv("ENABLE_TRANSCODING", "1")
    enabled = load_settings()
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(enabled), base_url="http://127.0.0.1:8000") as client:
        other = api.__class__(client, enabled)
        other.ready()
        analyzed = other.analyze("fixVP9opusA")
        converted = [item for item in analyzed["choices"] if item["kind"] == "mp4"]
        assert converted and converted[0]["requires_consent"]
        denied = other.create(analyzed, choice_id=converted[0]["choice_id"], key="no-consent-01", consent=False)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "CONSENT_REQUIRED"
        accepted = other.create(analyzed, choice_id=converted[0]["choice_id"], key="yes-consent1", consent=True)
        assert accepted.status_code == 202, accepted.text
        job = accepted.json()["id"]
        assert claim_next(enabled, "w2") == job
        process_job(enabled, job)
        finished = client.get(f"/api/v1/jobs/{job}").json()
        assert finished["status"] == "succeeded", finished


def test_idempotency_expiry_and_format_change(api, settings, media_root):
    api.ready()
    analysis = api.analyze("fixH264aacA")
    first = api.create(analysis, kind="mp4", key="same-key-0001")
    second = api.create(analysis, kind="mp4", key="same-key-0001")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    conflict = api.client.post(
        "/api/v1/jobs",
        json={"analysis_id": analysis["analysis_id"], "choice_id": analysis["choices"][0]["choice_id"], "keep_on_server": True, "conversion_consent": False},
        headers={**api.headers(), "Idempotency-Key": "same-key-0001"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    conn = connect(settings)
    try:
        conn.execute("UPDATE analyses SET expires_at = ? WHERE id = ?", (utc_iso(utc_now() - timedelta(minutes=1)), analysis["analysis_id"]))
    finally:
        conn.close()
    expired = api.create(analysis, kind="mp4", key="after-expiry1")
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "ANALYSIS_EXPIRED"
    # The queued job from before expiry is still claimable.
    assert claim_next(settings, "w") == first.json()["id"]
    process_job(settings, first.json()["id"])
    assert api.client.get(f"/api/v1/jobs/{first.json()['id']}").json()["status"] == "succeeded"

    fresh = api.analyze("fixChangedA")
    created = api.create(fresh, kind="mp4", key="change-key-01")
    job_id = created.json()["id"]
    catalog_path = settings.fixture_catalog
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["fixChangedA"]["file"] = str(media_root / "small.mp4")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    assert claim_next(settings, "w") == job_id
    process_job(settings, job_id)
    changed = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert changed["status"] == "failed"
    assert changed["error"]["code"] == "FORMAT_CHANGED"
    assert changed["file_state"] == "none"


def test_cancel_kills_sleeping_job(api, settings):
    api.ready()
    analysis = api.analyze("fixSleepAAA")
    created = api.create(analysis, kind="mp4", key="sleep-key-001")
    job_id = created.json()["id"]
    assert claim_next(settings, "w") == job_id
    thread = threading.Thread(target=process_job, args=(settings, job_id))
    thread.start()
    time.sleep(0.4)
    cancelled = api.client.post(f"/api/v1/jobs/{job_id}/cancel", headers=api.headers())
    assert cancelled.status_code == 200
    thread.join(timeout=15)
    assert not thread.is_alive()
    body = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "cancelled"
    assert body["file_state"] != "available"
    assert not (settings.files_dir / job_id).exists()


def test_invalid_output_is_not_success(api, settings):
    api.ready()
    for video_id, key in (("fixEmptyHkA", "empty-key-001"), ("fixTextHkAA", "text-key-0001")):
        analysis = api.analyze(video_id)
        created = api.create(analysis, kind="mp4", key=key)
        job_id = created.json()["id"]
        assert claim_next(settings, "w") == job_id
        process_job(settings, job_id)
        body = api.client.get(f"/api/v1/jobs/{job_id}").json()
        assert body["status"] == "failed", body
        assert body["error"]["code"] in {"OUTPUT_INVALID", "POSTPROCESS_FAILED"}
        missing = api.client.get(f"/api/v1/jobs/{job_id}/file")
        assert missing.status_code in {404, 410}


def test_ranges_expiry_and_retention(api, settings):
    api.ready()
    analysis = api.analyze("fixH264aacA")
    created = api.create(analysis, kind="mp4", key="range-key-001", keep=False)
    job_id = created.json()["id"]
    assert claim_next(settings, "w") == job_id
    process_job(settings, job_id)
    head = api.client.head(f"/api/v1/jobs/{job_id}/file")
    assert head.status_code == 200
    size = int(head.headers["content-length"])
    partial = api.client.get(f"/api/v1/jobs/{job_id}/file", headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206
    assert partial.content == api.client.get(f"/api/v1/jobs/{job_id}/file").content[:4]
    assert partial.headers["content-range"].startswith("bytes 0-3/")
    bad = api.client.get(f"/api/v1/jobs/{job_id}/file", headers={"Range": "bytes=9999999-9999999"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == f"bytes */{size}"
    conn = connect(settings)
    try:
        conn.execute(
            "UPDATE jobs SET file_expires_at = ?, keep_on_server = 0 WHERE id = ?",
            (utc_iso(utc_now() - timedelta(minutes=1)), job_id),
        )
        from app.services.storage import expire_finished_files

        expire_finished_files(conn, settings)
    finally:
        conn.close()
    expired = api.client.get(f"/api/v1/jobs/{job_id}/file")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "FILE_EXPIRED"
    unknown = api.client.get("/api/v1/jobs/does-not-exist/file")
    assert unknown.status_code == 404


def test_keep_and_history_delete(api, settings):
    api.ready()
    analysis = api.analyze("fixAudioAAA")
    created = api.create(analysis, kind="original_audio", key="keep-key-0001", keep=True)
    job_id = created.json()["id"]
    assert claim_next(settings, "w") == job_id
    process_job(settings, job_id)
    conn = connect(settings)
    try:
        from app.services.storage import expire_finished_files

        removed = expire_finished_files(conn, settings)
    finally:
        conn.close()
    assert removed == 0
    still = api.client.get(f"/api/v1/jobs/{job_id}/file")
    assert still.status_code == 200
    blocked = api.client.delete(f"/api/v1/jobs/{job_id}", headers=api.headers())
    assert blocked.status_code == 409
    deleted = api.client.delete(f"/api/v1/jobs/{job_id}/file", headers=api.headers())
    assert deleted.status_code == 200
    assert deleted.json()["file_state"] == "deleted"
    gone = api.client.delete(f"/api/v1/jobs/{job_id}", headers=api.headers())
    assert gone.status_code == 204


def test_restart_reconcile_and_competing_claims(api, settings):
    api.ready()
    analysis = api.analyze("fixH264aacA")
    created = api.create(analysis, kind="mp4", key="queue-key-001")
    job_id = created.json()["id"]
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as restarted:
        seen = restarted.get(f"/api/v1/jobs/{job_id}")
        assert seen.status_code == 401
    assert api.client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "queued"
    winners = []

    def claim():
        winners.append(claim_next(settings, "racer"))

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert winners.count(job_id) == 1
    conn = connect(settings)
    try:
        conn.execute(
            "UPDATE jobs SET status = 'running', phase = 'downloading' WHERE id = ?",
            (job_id,),
        )
    finally:
        conn.close()
    (settings.tmp_dir / job_id).mkdir(parents=True)
    (settings.tmp_dir / job_id / "partial.bin").write_bytes(b"partial")
    assert reconcile_abandoned(settings) >= 1
    body = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "interrupted"
    assert not (settings.tmp_dir / job_id).exists()


def test_security_boundaries(api, settings, tmp_path):
    api.ready()
    evil = api.client.post(
        "/api/v1/analyses",
        json={"url": "https://www.youtube.com/watch?v=fixH264aacA", "yt_dlp_args": "--exec rm"},
        headers=api.headers(),
    )
    assert evil.status_code == 400
    cross = api.client.post(
        "/api/v1/auth/logout",
        headers={**api.headers(), "Origin": "https://evil.example"},
    )
    assert cross.status_code == 403
    from fastapi.testclient import TestClient

    with TestClient(api.client.app, base_url="http://127.0.0.1:8000") as stranger:
        bare = stranger.get("/api/v1/jobs")
        assert bare.status_code == 401
    analysis = api.analyze("fixH264aacA")
    nasty = api.analyze("fixPort180A")
    assert "; rm" not in json.dumps(nasty["source"])
    created = api.create(analysis, kind="mp4", key="sec-key-00001")
    job_id = created.json()["id"]
    assert claim_next(settings, "w") == job_id
    process_job(settings, job_id)
    outside = tmp_path / "secret.txt"
    outside.write_text("top-secret", encoding="utf-8")
    link = settings.files_dir / job_id / "output.mp4"
    link.unlink()
    link.symlink_to(outside)
    leaked = api.client.get(f"/api/v1/jobs/{job_id}/file")
    assert leaked.status_code in {404, 410}
    assert b"top-secret" not in leaked.content
    assert ip_blocked("127.0.0.1")
    assert ip_blocked("169.254.169.254")
    assert ip_blocked("10.1.1.1")
    assert ip_blocked("::1")
    assert not ip_blocked("142.250.190.78")


def test_rate_limit_and_live(api, settings):
    api.ready()
    limited = api.client.post(
        "/api/v1/analyses",
        json={"url": "https://www.youtube.com/watch?v=fix429rateA"},
        headers=api.headers(),
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "SOURCE_RATE_LIMITED"
    state = settings.fixture_catalog.parent / "state" / "fix429rateA.probe_script"
    assert state.read_text(encoding="utf-8") == "1"
    again = api.client.post(
        "/api/v1/analyses",
        json={"url": "https://www.youtube.com/watch?v=fixH264aacA"},
        headers=api.headers(),
    )
    assert again.status_code == 429
    assert state.read_text(encoding="utf-8") == "1"
    conn = connect(settings)
    try:
        conn.execute("DELETE FROM provider_cooldown")
    finally:
        conn.close()
    live = api.client.post(
        "/api/v1/analyses",
        json={"url": "https://www.youtube.com/watch?v=fixLiveVidA"},
        headers=api.headers(),
    )
    assert live.status_code == 422
    assert live.json()["error"]["code"] == "SOURCE_UNAVAILABLE"


def test_403_refresh_then_success(api, settings):
    api.ready()
    analysis = api.analyze("fix403jobAA")
    created = api.create(analysis, kind="mp4", key="refresh-key01")
    job_id = created.json()["id"]
    assert claim_next(settings, "w") == job_id
    process_job(settings, job_id)
    body = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "succeeded", body


def test_playlist_flag(settings, media_root, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setenv("ENABLE_PLAYLISTS", "0")
    disabled = load_settings()
    with TestClient(create_app(disabled), base_url="http://127.0.0.1:8000") as client:
        gate = client.__class__  # silence
        api_disabled = __import__("tests.conftest", fromlist=["Api"]).Api(client, disabled)
        api_disabled.ready()
        rejected = client.post(
            "/api/v1/playlists/analyze",
            json={"url": "https://www.youtube.com/playlist?list=PLFIXTURE1"},
            headers=api_disabled.headers(),
        )
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "PLAYLISTS_DISABLED"
    monkeypatch.setenv("ENABLE_PLAYLISTS", "1")
    enabled = load_settings()
    with TestClient(create_app(enabled), base_url="http://127.0.0.1:8000") as client:
        api_enabled = __import__("tests.conftest", fromlist=["Api"]).Api(client, enabled)
        api_enabled.ready()
        accepted = client.post(
            "/api/v1/playlists/analyze",
            json={"url": "https://www.youtube.com/playlist?list=PLFIXTURE1"},
            headers=api_enabled.headers(),
        )
        assert accepted.status_code == 200, accepted.text
        payload = accepted.json()
        assert len(payload["entries"]) == 20
        assert payload["limited"] is True
        assert all(entry["position"] <= 20 for entry in payload["entries"])


def test_retry_parent_must_match(api, settings):
    api.ready()
    first = api.analyze("fixH264aacA")
    created = api.create(first, kind="mp4", key="parent-key-01")
    job_id = created.json()["id"]
    other = api.analyze("fixAudioAAA")
    response = api.client.post(
        f"/api/v1/jobs/{job_id}/retry",
        json={"analysis_id": other["analysis_id"], "choice_id": other["choices"][0]["choice_id"], "keep_on_server": False, "conversion_consent": False},
        headers={**api.headers(), "Idempotency-Key": "retry-key-0001"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PARENT_MISMATCH"
    extra = api.client.post(
        "/api/v1/jobs",
        json={"analysis_id": first["analysis_id"], "choice_id": first["choices"][0]["choice_id"], "keep_on_server": False, "conversion_consent": False, "parent_job_id": "nope"},
        headers={**api.headers(), "Idempotency-Key": "extra-parent01"},
    )
    assert extra.status_code == 400


def test_session_stream_closes_without_cancelling(api, settings):
    api.ready()
    analysis = api.analyze("fixH264aacA")
    created = api.create(analysis, kind="mp4", key="sse-key-00001")
    job_id = created.json()["id"]
    conn = connect(settings)
    try:
        conn.execute("UPDATE sessions SET expires_at = ? ", (utc_iso(utc_now() + timedelta(seconds=0.4)),))
    finally:
        conn.close()
    with api.client.stream("GET", f"/api/v1/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        text = ""
        for chunk in response.iter_text():
            text += chunk
            if "authenticated" in text or len(text) > 5000:
                break
    assert "authenticated" in text or "snapshot" in text
    assert api.client.get(f"/api/v1/jobs/{job_id}").status_code == 401
    # A fresh login must see the same queued job, not a duplicate.
    api.login()
    seen = api.client.get(f"/api/v1/jobs/{job_id}").json()
    assert seen["status"] == "queued"
    assert seen["id"] == job_id
