"""T16. Opt-in only. Default CI must not contact YouTube."""

from __future__ import annotations

import json
import os
import sqlite3
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.worker import claim_next, process_job

URL = os.environ.get("LIVE_TEST_URL", "").strip()
FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"
DENO = os.environ.get("DENO_PATH") or shutil.which("deno") or "deno"


@pytest.mark.skipif(
    not URL,
    reason="T16 skipped on 2026-10-18: LIVE_TEST_URL was not provided. Local fixtures do not prove YouTube availability.",
)
@pytest.mark.parametrize("kind", ["mp4", "mp3"])
def test_live_source_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str):
    from fastapi.testclient import TestClient

    from tests.conftest import Api

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDIA_ADAPTER", "ytdlp")
    monkeypatch.setenv("ALLOW_FIXTURE_URLS", "0")
    monkeypatch.setenv("ALLOW_HTTP_BOOTSTRAP", "1")
    monkeypatch.setenv("LOCAL_HTTP", "1")
    monkeypatch.setenv("FFMPEG_PATH", FFMPEG)
    monkeypatch.setenv("FFPROBE_PATH", FFPROBE)
    monkeypatch.setenv("DENO_PATH", DENO)
    monkeypatch.setenv("MIN_FREE_BYTES", "0")
    monkeypatch.setenv("ENABLE_PLAYLISTS", "0")
    monkeypatch.setenv("ENABLE_TRANSCODING", "0")
    settings = load_settings()
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as client:
        api = Api(client, settings)
        api.ready()
        analyzed = client.post("/api/v1/analyses", json={"url": URL}, headers=api.headers())
        assert analyzed.status_code == 200, analyzed.text
        analysis = analyzed.json()
        created = api.create(analysis, kind=kind, key=f"live-smoke-{kind}")
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        assert claim_next(settings, "live-smoke") == job_id
        process_job(settings, job_id)
        done = client.get(f"/api/v1/jobs/{job_id}", headers=api.headers())
        body = done.json()
        assert body["status"] == "succeeded", body
        db = sqlite3.connect(settings.db_path)
        row = db.execute("SELECT artifact_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
        db.close()
        artifact = json.loads(row[0])
        media = settings.data_dir / artifact["relative_path"]
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-show_streams", "-of", "json", str(media)],
            capture_output=True,
            text=True,
            check=False,
        )
        record = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "adapter": "ytdlp",
            "job_status": body["status"],
            "bytes": media.stat().st_size,
            "ffprobe_returncode": probe.returncode,
            "streams": json.loads(probe.stdout) if probe.returncode == 0 else probe.stderr[-500:],
        }
        (tmp_path / "live-smoke.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        assert probe.returncode == 0
        assert media.stat().st_size > 0
