"""Personal local mode keeps browser protections without password prompts.

All state lives in pytest's temporary SQLite store. Downloads use synthetic
media; these regressions never contact YouTube or touch an operator's data.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import connect, utc_iso, utc_now
from app.main import create_app
from app.security import hash_token, verify_password
from app.worker import claim_next, process_job
from conftest import Api, PASSWORD


@pytest.fixture
def personal_settings(settings):
    return replace(settings, require_password=False, allow_http_bootstrap=False)


@pytest.fixture
def personal_client(personal_settings):
    with TestClient(create_app(personal_settings), base_url="http://127.0.0.1:8000") as client:
        yield client


def enter(client, settings):
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["authenticated"] is True
    assert session["password_required"] is False
    assert session["bootstrap_allowed"] is False
    assert session["bootstrap_method"] is None
    assert session["csrf_token"]
    api = Api(client, settings)
    api.csrf = session["csrf_token"]
    return api, response


@pytest.mark.parametrize("local_http", [True, False])
def test_personal_first_visit_needs_neither_bootstrap_nor_login(settings, local_http):
    cfg = replace(settings, require_password=False, allow_http_bootstrap=False, local_http=local_http)
    scheme = "http" if local_http else "https"
    with TestClient(create_app(cfg), base_url=f"{scheme}://127.0.0.1:8000") as client:
        _, response = enter(client, cfg)
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert ("Secure" in cookie) is (not local_http)
        assert client.get("/api/v1/settings").json()["language"] == "ko"
        assert client.get("/api/v1/jobs").status_code == 200
        conn = connect(cfg)
        try:
            assert conn.execute("SELECT COUNT(*) FROM operator").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == 1
        finally:
            conn.close()


def test_personal_reload_reuses_automatic_session(personal_client, personal_settings):
    api, _ = enter(personal_client, personal_settings)
    token = personal_client.cookies.get(personal_settings.cookie_name)
    next_visit = personal_client.get("/api/v1/auth/session")
    assert next_visit.status_code == 200
    assert next_visit.json()["csrf_token"] == api.csrf
    assert "set-cookie" not in next_visit.headers
    assert personal_client.cookies.get(personal_settings.cookie_name) == token
    conn = connect(personal_settings)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize("lost_state", ["cookie_deleted", "cookie_invalid", "expired", "revoked", "logout"])
def test_personal_session_recovers_without_password(personal_client, personal_settings, lost_state):
    api, _ = enter(personal_client, personal_settings)
    original_token = personal_client.cookies.get(personal_settings.cookie_name)
    conn = connect(personal_settings)
    try:
        if lost_state == "cookie_deleted":
            personal_client.cookies.clear()
        elif lost_state == "cookie_invalid":
            personal_client.cookies.clear()
            personal_client.cookies.set(
                personal_settings.cookie_name, "unrecognized-token", domain="127.0.0.1", path="/"
            )
        elif lost_state == "expired":
            conn.execute("UPDATE sessions SET expires_at = ?", (utc_iso(utc_now() - timedelta(seconds=1)),))
        elif lost_state == "revoked":
            conn.execute("UPDATE sessions SET revoked_at = ?", (utc_iso(),))
        else:
            assert personal_client.post("/api/v1/auth/logout", headers=api.headers()).status_code == 200
        # A write/read never silently bypasses session validation. The app's
        # regular initial session request restores access automatically.
        assert personal_client.get("/api/v1/jobs").status_code == 401
        replacement, response = enter(personal_client, personal_settings)
        assert "set-cookie" in response.headers
        assert personal_client.cookies.get(personal_settings.cookie_name) != original_token
        assert replacement.csrf != api.csrf
        assert personal_client.get("/api/v1/jobs").status_code == 200
        stale = personal_client.patch(
            "/api/v1/settings", json={"theme": "dark"}, headers=api.headers()
        )
        assert stale.status_code == 403
        assert stale.json()["error"]["code"] == "CSRF_FAILED"
    finally:
        conn.close()


@pytest.mark.parametrize("path", ["/api/v1/auth/session", "/api/v1/jobs", "/api/v1/settings"])
def test_personal_host_guard_survives_passwordless_mode(personal_client, personal_settings, path):
    enter(personal_client, personal_settings)
    response = personal_client.get(path, headers={"Host": "attacker.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.parametrize("changes", [
    {"Origin": None},
    {"Origin": "https://attacker.example"},
    {"Origin": "http://127.0.0.1:9999"},
    {"X-CSRF-Token": None},
    {"X-CSRF-Token": "invalid-csrf"},
    {"X-Requested-With": None},
    {"X-Requested-With": "another-app"},
    {"Host": "attacker.example", "Origin": "http://attacker.example"},
])
def test_personal_writes_still_require_origin_and_csrf(personal_client, personal_settings, changes):
    api, _ = enter(personal_client, personal_settings)
    headers = api.headers()
    for name, value in changes.items():
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
    response = personal_client.patch("/api/v1/settings", json={"theme": "dark"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"
    assert personal_client.get("/api/v1/settings").json()["theme"] == "system"


def test_switching_to_personal_preserves_existing_operator_jobs_and_preferences(settings):
    protected = replace(settings, require_password=True)
    with TestClient(create_app(protected), base_url="http://127.0.0.1:8000") as client:
        api = Api(client, protected)
        api.ready()
        assert client.patch(
            "/api/v1/settings", json={"language": "en", "theme": "dark", "mp3_bitrate": 320}, headers=api.headers()
        ).status_code == 200
        job = api.create(api.analyze(), key="preserved-job-0001")
        assert job.status_code == 202
        job_id = job.json()["id"]
    conn = connect(settings)
    try:
        previous = {
            table: dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (value,)).fetchone())
            for table, value in (("operator", 1), ("preferences", 1), ("jobs", job_id))
        }
    finally:
        conn.close()
    personal = replace(settings, require_password=False, allow_http_bootstrap=False)
    with TestClient(create_app(personal), base_url="http://127.0.0.1:8000") as client:
        _, response = enter(client, personal)
        assert response.json()["language"] == "en"
        assert response.json()["theme"] == "dark"
        assert client.get(f"/api/v1/jobs/{job_id}").json()["id"] == job_id
        assert client.get("/api/v1/settings").json()["mp3_bitrate"] == 320
    conn = connect(settings)
    try:
        for table, value in (("operator", 1), ("preferences", 1), ("jobs", job_id)):
            row = dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (value,)).fetchone())
            assert row == previous[table]
        assert verify_password(PASSWORD, previous["operator"]["password_hash"])
    finally:
        conn.close()
    # Re-enabling the protected profile retains the original credential.
    with TestClient(create_app(protected), base_url="http://127.0.0.1:8000") as client:
        session = client.get("/api/v1/auth/session").json()
        assert session["authenticated"] is False
        assert session["password_required"] is True
        assert session["bootstrapped"] is True
        assert client.get("/api/v1/jobs").status_code == 401
        Api(client, protected).login()
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200


def test_protected_first_visit_still_requires_password_setup(settings):
    cfg = replace(settings, require_password=True, allow_http_bootstrap=False)
    with TestClient(create_app(cfg), base_url="http://127.0.0.1:8000") as client:
        response = client.get("/api/v1/auth/session")
        assert response.json()["authenticated"] is False
        assert response.json()["password_required"] is True
        assert response.json()["bootstrapped"] is False
        assert "set-cookie" not in response.headers
        assert client.get("/api/v1/jobs").status_code == 401


@pytest.mark.parametrize("kind,video_id,content_type", [
    ("mp4", "fixH264aacA", "video/mp4"),
    ("mp3", "fixAudioAAA", "audio/mpeg"),
])
def test_personal_fixture_download_without_bootstrap_or_login(
    personal_client, personal_settings, kind, video_id, content_type
):
    api, _ = enter(personal_client, personal_settings)
    created = api.create(api.analyze(video_id), kind=kind, key=f"passwordless-{kind}-0001")
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    assert claim_next(personal_settings, "passwordless-fixture-worker") == job_id
    process_job(personal_settings, job_id)
    finished = personal_client.get(f"/api/v1/jobs/{job_id}")
    assert finished.json()["status"] == "succeeded", finished.text
    saved = personal_client.get(f"/api/v1/jobs/{job_id}/file")
    assert saved.status_code == 200
    assert saved.headers["content-type"].startswith(content_type)
    assert f".{kind}" in saved.headers["content-disposition"]
    assert len(saved.content) > 100
    conn = connect(personal_settings)
    try:
        assert conn.execute("SELECT COUNT(*) FROM operator").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 0
        # Only a one-way digest of the automatic cookie is persisted.
        token = personal_client.cookies.get(personal_settings.cookie_name)
        assert conn.execute("SELECT token_hash FROM sessions").fetchone()[0] == hash_token(token)
    finally:
        conn.close()
