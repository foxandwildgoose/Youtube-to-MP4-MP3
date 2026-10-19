"""Synthetic SQLite/filesystem regressions; no provider or media network calls."""

from __future__ import annotations

import json
import os
import asyncio
import sqlite3
import threading
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app import db
from app.config import load_settings
from app.db import connect, init_db, transaction, utc_iso, utc_now
from app.errors import AppError
from app.services.jobs import create_job, delete_file, delete_history, list_jobs, request_cancel, set_retention, validate_retry_parent
from app.services.storage import (
    active_leases, directory_size, expire_finished_files, job_final_dir,
    open_artifact, outstanding_reservations, prune_metadata, prune_old_history,
    publish_file, recheck_reservation, release_lease, renew_lease,
)


@pytest.fixture
def cfg(tmp_path):
    settings = replace(load_settings(), data_dir=tmp_path / "data", max_workspace_bytes=1024 * 1024,
                       max_input_bytes=512 * 1024, max_output_bytes=512 * 1024,
                       max_storage_bytes=64 * 1024 * 1024, min_free_bytes=0,
                       max_waiting_jobs=20, history_retention_seconds=86400)
    init_db(settings).close()
    return settings


def analysis(conn, analysis_id="analysis", *, kind="mp4", title="긴 제목의 파일", expires=None):
    contract = {"kind": kind, "ext": "mp4" if kind == "mp4" else "mp3", "label": "MP4 720p", "size_estimate": None}
    conn.execute("INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?)", (
        analysis_id, "https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk",
        json.dumps({"title": title, "channel": "채널", "duration_seconds": 1}),
        json.dumps([{"choice_id": "choice", "contract": contract}]), utc_iso(),
        expires or utc_iso(utc_now() + timedelta(minutes=10)),
    ))


def create(conn, cfg, key="key-0000001", **kwargs):
    return create_job(conn, cfg, analysis_id="analysis", choice_id="choice", keep_on_server=False,
                      conversion_consent=False, idempotency_key=key, request_hash=key, **kwargs)


def artifact(conn, cfg, *, key="artifact-key", expired=False, keep=False):
    job = create(conn, cfg, key)
    path = job_final_dir(cfg, job["id"])
    path.mkdir()
    payload = b"fixture-file-bytes" * 1024
    (path / "output.mp4").write_bytes(payload)
    expiry = utc_iso(utc_now() + timedelta(seconds=-10 if expired else 3600))
    conn.execute("UPDATE jobs SET status = 'succeeded', file_state = 'available', keep_on_server = ?, file_expires_at = ?, artifact_json = ? WHERE id = ?", (
        int(keep), None if keep else expiry,
        json.dumps({"relative_path": f"files/{job['id']}/output.mp4", "filename": "한글 파일.mp4", "mime": "video/mp4", "bytes": len(payload)}), job["id"],
    ))
    return job["id"], payload, path / "output.mp4"


@pytest.mark.parametrize("same_key", [False, True])
def test_atomic_admission_distinct_and_identical_keys(cfg, same_key):
    cfg = replace(cfg, max_waiting_jobs=1)
    conn = connect(cfg)
    analysis(conn)
    conn.close()
    start = threading.Barrier(2)
    results = []

    def submit(index):
        connection = connect(cfg)
        start.wait()
        try:
            results.append(create(connection, cfg, "identical-key" if same_key else f"distinct-key-{index}"))
        except AppError as exc:
            results.append(exc.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=submit, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    conn = connect(cfg)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM storage_reservations").fetchone()[0] == 1
    conn.close()
    if same_key:
        assert results[0]["id"] == results[1]["id"]
    else:
        assert results.count("LIMIT_EXCEEDED") == 1


def test_unknown_reservation_capacity_and_terminal_release(cfg):
    conn = connect(cfg)
    analysis(conn)
    first = create(conn, cfg)
    charged = conn.execute("SELECT reserved_bytes FROM storage_reservations").fetchone()[0]
    assert charged == cfg.max_workspace_bytes
    restricted = replace(cfg, max_storage_bytes=directory_size(cfg.data_dir) + charged + 8192)
    with pytest.raises(AppError, match="STORAGE_FULL"):
        create(conn, restricted, "another-key")
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    request_cancel(conn, first["id"])
    assert conn.execute("SELECT COUNT(*) FROM storage_reservations").fetchone()[0] == 0
    conn.close()


def test_written_workspace_replaces_reservation_and_claim_rechecks(cfg):
    conn = connect(cfg)
    analysis(conn)
    job = create(conn, cfg)
    workspace = cfg.tmp_dir / job["id"]
    workspace.mkdir()
    (workspace / "input").write_bytes(b"x" * 400_000)
    assert outstanding_reservations(conn, cfg) == cfg.max_workspace_bytes - 400_000
    restricted = replace(cfg, max_storage_bytes=directory_size(cfg.data_dir) + cfg.max_workspace_bytes - 400_000 + 1024)
    recheck_reservation(conn, restricted, job["id"])
    with pytest.raises(AppError, match="STORAGE_FULL"):
        recheck_reservation(conn, replace(cfg, max_storage_bytes=1), job["id"])
    conn.execute("UPDATE jobs SET status = 'interrupted' WHERE id = ?", (job["id"],))
    assert conn.execute("SELECT COUNT(*) FROM storage_reservations").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_history_and_retry_rejected_without_losing_control(cfg, status):
    conn = connect(cfg)
    analysis(conn)
    job = create(conn, cfg)
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job["id"]))
    with pytest.raises(AppError, match="HISTORY_ACTIVE"):
        delete_history(conn, job["id"])
    with pytest.raises(AppError, match="RETRY_NOT_ALLOWED"):
        validate_retry_parent(conn, job["id"])
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (job["id"],)).fetchone()[0] == status
    conn.close()


def test_deleted_job_replay_is_tombstone_conflict(cfg):
    conn = connect(cfg)
    analysis(conn)
    job = create(conn, cfg)
    request_cancel(conn, job["id"])
    delete_history(conn, job["id"])
    delete_history(conn, job["id"])
    with pytest.raises(AppError, match="IDEMPOTENCY_CONFLICT"):
        create(conn, cfg)
    tombstone = conn.execute("SELECT job_id, expires_at FROM idempotency_keys").fetchone()
    assert tombstone["job_id"] is None and tombstone["expires_at"] > utc_iso()
    conn.close()


def test_same_key_conflicting_payload_never_creates_another_job(cfg):
    conn = connect(cfg)
    analysis(conn)
    create(conn, cfg)
    with pytest.raises(AppError, match="IDEMPOTENCY_CONFLICT"):
        create_job(conn, cfg, analysis_id="analysis", choice_id="choice", keep_on_server=True,
                   conversion_consent=False, idempotency_key="key-0000001", request_hash="changed-payload")
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    conn.close()


def test_open_lease_excludes_delete_and_survives_external_unlink(cfg):
    conn = connect(cfg)
    analysis(conn)
    job_id, payload, path = artifact(conn, cfg)
    opened = open_artifact(conn, cfg, job_id)
    assert active_leases(conn, job_id)
    with pytest.raises(AppError):
        delete_file(conn, cfg, job_id)
    # Supported Linux semantics: the opened inode remains readable after unlink.
    path.unlink()
    assert opened.handle.read() == payload
    opened.handle.close()
    release_lease(conn, opened.lease_id)
    assert not active_leases(conn, job_id)
    delete_file(conn, cfg, job_id)
    conn.close()


def test_access_time_ttl_pin_and_renewal(cfg, monkeypatch):
    conn = connect(cfg)
    analysis(conn)
    expired_id, _, path = artifact(conn, cfg, expired=True)
    with pytest.raises(AppError, match="FILE_EXPIRED"):
        open_artifact(conn, cfg, expired_id)
    assert not path.exists()
    with pytest.raises(AppError, match="FILE_EXPIRED"):
        set_retention(conn, cfg, expired_id, True)
    job_id, payload, _ = artifact(conn, cfg, key="leased-key")
    opened = open_artifact(conn, cfg, job_id)
    from app.services import storage
    clock = utc_now() + timedelta(minutes=11)
    monkeypatch.setattr(storage, "utc_now", lambda: clock)
    assert renew_lease(conn, opened.lease_id)
    expires = conn.execute("SELECT expires_at FROM transfer_leases WHERE id = ?", (opened.lease_id,)).fetchone()[0]
    assert expires > utc_iso(clock)
    assert opened.handle.read() == payload
    opened.handle.close()
    release_lease(conn, opened.lease_id)
    conn.close()


@pytest.mark.parametrize("attack", ["outside", "state", "relative", "directory"])
def test_exact_subtree_no_follow_filesystem_hardening(cfg, tmp_path, attack):
    conn = connect(cfg)
    analysis(conn)
    job_id, _, path = artifact(conn, cfg)
    secret = cfg.db_path if attack == "state" else tmp_path / "secret"
    if attack != "state":
        secret.write_bytes(b"SECRET")
    if attack == "relative":
        record = json.loads(conn.execute("SELECT artifact_json FROM jobs WHERE id = ?", (job_id,)).fetchone()[0])
        record["relative_path"] = "state/app.db"
        conn.execute("UPDATE jobs SET artifact_json = ? WHERE id = ?", (json.dumps(record), job_id))
    elif attack == "directory":
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(secret.parent, target_is_directory=True)
    else:
        path.unlink()
        path.symlink_to(secret)
    with pytest.raises(AppError, match="FILE_MISSING"):
        open_artifact(conn, cfg, job_id)
    assert not active_leases(conn, job_id)
    conn.close()


def test_directory_swap_after_open_keeps_exact_original_inode(cfg, monkeypatch):
    """Conditional local filesystem hardening, not a remote exploit claim."""
    from app.services import storage

    conn = connect(cfg)
    analysis(conn)
    job_id, payload, path = artifact(conn, cfg)
    real_open = os.open
    moved = path.parent.with_name(job_id + "_moved")
    (cfg.db_path.parent / "output.mp4").write_bytes(b"SECRET-STATE-BYTES")

    def swap_open(component, flags, *args, **kwargs):
        descriptor = real_open(component, flags, *args, **kwargs)
        if component == job_id:
            path.parent.rename(moved)
            path.parent.symlink_to(cfg.db_path.parent, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(storage.os, "open", swap_open)
    opened = open_artifact(conn, cfg, job_id)
    assert opened.handle.read() == payload
    opened.handle.close()
    release_lease(conn, opened.lease_id)
    conn.close()


def test_publication_source_swap_cannot_publish_a_symlink(cfg, tmp_path, monkeypatch):
    from app.services import storage

    workspace = cfg.tmp_dir / "publication_job"
    workspace.mkdir()
    staged = workspace / "final.mp4"
    staged.write_bytes(b"GOOD-STAGED-MEDIA")
    secret = tmp_path / "private-state"
    secret.write_bytes(b"SECRET")
    real_replace = os.replace

    def swap_then_replace(source, destination, **kwargs):
        staged.unlink()
        staged.symlink_to(secret)
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(storage.os, "replace", swap_then_replace)
    with pytest.raises(AppError, match="OUTPUT_INVALID"):
        publish_file(cfg, "publication_job", staged, "download.mp4")
    assert secret.read_bytes() == b"SECRET"
    assert not (cfg.files_dir / "publication_job" / "output.mp4").exists()


def test_valid_publication_is_exact_atomic_output(cfg):
    workspace = cfg.tmp_dir / "publication_job"
    workspace.mkdir()
    staged = workspace / "final.mp4"
    staged.write_bytes(b"GOOD-STAGED-MEDIA")
    published = publish_file(cfg, "publication_job", staged, "download.mp4")
    assert published == cfg.files_dir / "publication_job" / "output.mp4"
    assert published.read_bytes() == b"GOOD-STAGED-MEDIA" and not staged.exists()


def test_expiry_lease_and_retention_interleavings(cfg):
    conn = connect(cfg)
    analysis(conn)
    job_id, payload, path = artifact(conn, cfg)
    opened = open_artifact(conn, cfg, job_id)
    conn.execute("UPDATE jobs SET file_expires_at = ? WHERE id = ?", (utc_iso(utc_now() - timedelta(seconds=1)), job_id))
    assert expire_finished_files(conn, cfg) == 0
    assert path.exists() and opened.handle.read() == payload
    opened.handle.close()
    release_lease(conn, opened.lease_id)
    assert expire_finished_files(conn, cfg) == 1
    assert not path.exists()
    kept_id, _, kept_path = artifact(conn, cfg, key="kept-key", keep=True)
    assert expire_finished_files(conn, cfg) == 0 and kept_path.exists()
    assert set_retention(conn, cfg, kept_id, False)["keep_on_server"] is False
    conn.close()


def test_metadata_retention_preserves_active_kept_and_retry_references(cfg):
    conn = connect(cfg)
    expired = utc_iso(utc_now() - timedelta(days=2))
    analysis(conn, expires=expired)
    analysis(conn, "unreferenced", expires=expired)
    conn.execute("UPDATE analyses SET expires_at = ? WHERE id = 'analysis'", (utc_iso(utc_now() + timedelta(minutes=1)),))
    active = create(conn, cfg)
    conn.execute("UPDATE analyses SET expires_at = ? WHERE id = 'analysis'", (expired,))
    conn.execute("INSERT INTO sessions VALUES ('expired', 'hash', 'csrf', ?, ?, NULL, NULL)", (expired, expired))
    conn.execute("INSERT INTO transfer_leases VALUES ('stale', ?, ?)", (active["id"], expired))
    prune_metadata(conn, cfg)
    assert conn.execute("SELECT id FROM analyses").fetchall()[0][0] == "analysis"
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM transfer_leases").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM storage_reservations").fetchone()[0] == 1
    request_cancel(conn, active["id"])
    conn.execute("UPDATE jobs SET created_at = ?", (expired,))
    assert prune_old_history(conn, cfg) == 1
    assert conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
    assert conn.execute("SELECT job_id FROM idempotency_keys").fetchone()[0] is None
    conn.close()


def test_pruning_kept_artifacts_and_required_retry_ancestry(cfg):
    conn = connect(cfg)
    analysis(conn)
    kept_id, payload, kept_path = artifact(conn, cfg, keep=True)
    parent = create(conn, cfg, "parent-key")
    request_cancel(conn, parent["id"])
    child = create(conn, cfg, "child-key", parent_job_id=parent["id"])
    old = utc_iso(utc_now() - timedelta(days=2))
    conn.execute("UPDATE jobs SET created_at = ?", (old,))
    assert prune_old_history(conn, cfg) == 0
    assert kept_path.read_bytes() == payload
    assert conn.execute("SELECT 1 FROM jobs WHERE id = ?", (parent["id"],)).fetchone()
    delete_history(conn, parent["id"])
    assert conn.execute("SELECT history_hidden FROM jobs WHERE id = ?", (parent["id"],)).fetchone()[0] == 1
    request_cancel(conn, child["id"])
    assert prune_old_history(conn, cfg) == 1
    assert prune_old_history(conn, cfg) == 1
    assert conn.execute("SELECT id FROM jobs").fetchone()[0] == kept_id
    assert kept_path.read_bytes() == payload
    conn.close()


def test_search_paging_filters_include_older_kept_file(cfg):
    conn = connect(cfg)
    analysis(conn)
    kept_id, _, _ = artifact(conn, cfg, keep=True)
    for index in range(35):
        job = create(conn, cfg, f"record-{index}")
        request_cancel(conn, job["id"])
    results = list_jobs(conn, active=False, file_state="available", search="긴 제목", format="mp4", limit=10, offset=0)
    assert results["total"] == 1 and results["jobs"][0]["id"] == kept_id
    assert results["offset"] == 0 and results["limit"] == 10
    assert list_jobs(conn, active=False, limit=30, offset=30)["total"] == 36
    assert len(list_jobs(conn, active=False, limit=30, offset=30)["jobs"]) == 6
    assert list_jobs(conn, search="%", limit=30)["total"] == 0
    conn.close()


def test_migration_rollback_and_existing_data_preserved(cfg, tmp_path, monkeypatch):
    conn = connect(cfg)
    analysis(conn)
    job_id, payload, path = artifact(conn, cfg, keep=True)
    before = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0003_fail.sql").write_text("CREATE TABLE should_rollback(id INTEGER);\nINSERT INTO missing_table VALUES (1);\n", encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATIONS", migrations)
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'should_rollback'").fetchone()
    assert not conn.execute("SELECT 1 FROM schema_migrations WHERE version = 3").fetchone()
    assert dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()) == dict(before)
    assert path.read_bytes() == payload
    conn.close()


def test_existing_0001_database_and_kept_file_migrate_without_loss(cfg, tmp_path, monkeypatch):
    original = db.MIGRATIONS
    legacy_scripts = tmp_path / "legacy_migrations"
    legacy_scripts.mkdir()
    (legacy_scripts / "0001_init.sql").write_text((original / "0001_init.sql").read_text(), encoding="utf-8")
    legacy = replace(cfg, data_dir=tmp_path / "legacy_data")
    monkeypatch.setattr(db, "MIGRATIONS", legacy_scripts)
    conn = init_db(legacy)
    now = utc_iso()
    conn.execute("INSERT INTO jobs(id, status, file_state, keep_on_server, revision, contract_json, source_json, created_at, updated_at) VALUES ('kept_legacy', 'succeeded', 'available', 1, 7, '{}', '{}', ?, ?)", (now, now))
    keeper = legacy.files_dir / "kept_legacy"
    keeper.mkdir()
    (keeper / "output.mp4").write_bytes(b"LEGACY-KEPT-MEDIA")
    monkeypatch.setattr(db, "MIGRATIONS", original)
    db.migrate(conn)
    row = conn.execute("SELECT * FROM jobs WHERE id = 'kept_legacy'").fetchone()
    assert row["keep_on_server"] == 1 and row["revision"] == 7 and row["file_state"] == "available"
    assert row["next_attempt_at"] is None and row["refresh_403_used"] == 0
    assert (keeper / "output.mp4").read_bytes() == b"LEGACY-KEPT-MEDIA"
    assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    conn.close()


def test_nested_transaction_rollback_is_local(cfg):
    conn = connect(cfg)
    with transaction(conn):
        analysis(conn)
        with pytest.raises(ValueError):
            with transaction(conn):
                conn.execute("DELETE FROM analyses")
                raise ValueError("abort inner work")
        assert conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1
    assert not conn.in_transaction
    conn.close()


@pytest.mark.parametrize("operation", ["delete", "expire", "pin"])
def test_asgi_download_start_interleaves_with_file_lifecycle(cfg, operation):
    """Pause an authenticated ASGI transfer after headers, race real services."""
    from app.main import create_app
    from app.security import create_session

    conn = connect(cfg)
    analysis(conn)
    job_id, payload, path = artifact(conn, cfg)
    _, token, _ = create_session(conn, cfg)
    app = create_app(cfg)
    begun, proceed = threading.Event(), threading.Event()
    messages, failures = [], []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            begun.set()
            assert await asyncio.to_thread(proceed.wait, 5)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": "GET", "scheme": "http", "root_path": "",
             "path": f"/api/v1/jobs/{job_id}/file", "raw_path": f"/api/v1/jobs/{job_id}/file".encode(),
             "query_string": b"", "headers": [(b"host", b"127.0.0.1"),
               (b"cookie", f"{cfg.cookie_name}={token}".encode())],
             "client": ("127.0.0.1", 12000), "server": ("127.0.0.1", 80)}

    def run():
        try:
            asyncio.run(app(scope, receive, send))
        except BaseException as exc:
            failures.append(exc)

    transfer = threading.Thread(target=run)
    transfer.start()
    assert begun.wait(5)
    try:
        assert active_leases(conn, job_id)
        if operation == "delete":
            with pytest.raises(AppError) as busy:
                delete_file(conn, cfg, job_id)
            assert busy.value.status == 409
        elif operation == "expire":
            conn.execute("UPDATE jobs SET file_expires_at = ? WHERE id = ?", (utc_iso(utc_now() - timedelta(seconds=1)), job_id))
            assert expire_finished_files(conn, cfg) == 0
        else:
            assert set_retention(conn, cfg, job_id, True)["keep_on_server"]
        assert path.exists()
    finally:
        proceed.set()
        transfer.join(timeout=10)
    assert not transfer.is_alive() and not failures
    assert messages[0]["status"] == 200
    assert b"".join(message.get("body", b"") for message in messages) == payload
    assert not active_leases(conn, job_id)
    conn.close()


def test_asgi_disconnect_releases_lease(cfg):
    from app.main import create_app
    from app.security import create_session

    conn = connect(cfg)
    analysis(conn)
    job_id, _, _ = artifact(conn, cfg)
    _, token, _ = create_session(conn, cfg)
    messages = []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            raise OSError("synthetic disconnected client")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": "GET", "scheme": "http", "root_path": "",
             "path": f"/api/v1/jobs/{job_id}/file", "raw_path": f"/api/v1/jobs/{job_id}/file".encode(),
             "query_string": b"", "headers": [(b"host", b"127.0.0.1"),
                (b"cookie", f"{cfg.cookie_name}={token}".encode())],
             "client": ("127.0.0.1", 12000), "server": ("127.0.0.1", 80)}
    from starlette.requests import ClientDisconnect
    with pytest.raises((ClientDisconnect, OSError)):
        asyncio.run(create_app(cfg)(scope, receive, send))
    assert messages[0]["status"] == 200
    assert not active_leases(conn, job_id)
    conn.close()


def test_http_ranges_head_unicode_and_unswept_expiry(cfg):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.security import create_session

    conn = connect(cfg)
    analysis(conn)
    job_id, payload, _ = artifact(conn, cfg)
    _, token, _ = create_session(conn, cfg)
    with TestClient(create_app(cfg), base_url="http://127.0.0.1") as client:
        client.cookies.set(cfg.cookie_name, token)
        head = client.head(f"/api/v1/jobs/{job_id}/file")
        assert head.status_code == 200 and int(head.headers["content-length"]) == len(payload)
        assert head.content == b"" and not active_leases(conn, job_id)
        assert "filename*=UTF-8''" in head.headers["content-disposition"]
        for header, expected in (("bytes=-17", payload[-17:]), ("bytes=17-", payload[17:]), ("bytes=2-7", payload[2:8])):
            response = client.get(f"/api/v1/jobs/{job_id}/file", headers={"Range": header})
            assert response.status_code == 206 and response.content == expected
            assert not active_leases(conn, job_id)
        invalid = client.get(f"/api/v1/jobs/{job_id}/file", headers={"Range": f"bytes={len(payload)}-"})
        assert invalid.status_code == 416 and invalid.headers["content-range"] == f"bytes */{len(payload)}"
        assert not active_leases(conn, job_id)
        conn.execute("UPDATE jobs SET file_expires_at = ? WHERE id = ?", (utc_iso(utc_now() - timedelta(seconds=1)), job_id))
        expired = client.get(f"/api/v1/jobs/{job_id}/file")
        assert expired.status_code == 410 and expired.json()["error"]["code"] == "FILE_EXPIRED"
    conn.close()
