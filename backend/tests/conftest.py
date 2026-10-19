"""Shared fixtures. Media is synthetic; nothing here contacts YouTube."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.security import operator_exists, set_password
from app.db import connect

def tool(name: str, variable: str) -> str:
    return os.environ.get(variable) or shutil.which(name) or name


FFMPEG = tool("ffmpeg", "FFMPEG_PATH")
FFPROBE = tool("ffprobe", "FFPROBE_PATH")
DENO = tool("deno", "DENO_PATH")
PASSWORD = "local-password-1"


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])


@pytest.fixture(scope="session")
def media_root(tmp_path_factory) -> Path:
    for path in (FFMPEG, FFPROBE):
        if not shutil.which(path):
            pytest.fail(f"Required media tool not found: {path}. Set FFMPEG_PATH/FFPROBE_PATH or install on PATH.")
    proc = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True)
    for encoder in ("libx264", "aac", "libmp3lame", "libvpx-vp9", "libopus"):
        if encoder not in proc.stdout:
            pytest.fail(f"Required fixture encoder missing: {encoder}")
    root = tmp_path_factory.mktemp("media")
    _run(
        [
            FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-c:a", "aac", "-shortest", "-metadata:s:a:0", "language=kor",
            str(root / "h264.mp4"),
        ]
    )
    _run(
        [
            FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            "-metadata:s:a:0", "language=kor",
            str(root / "portrait.mp4"),
        ]
    )
    _run(
        [
            FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "200k",
            "-c:a", "libopus", "-shortest",
            str(root / "vp9.webm"),
        ]
    )
    _run(
        [
            FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
            "-c:a", "aac", "-metadata:s:a:0", "language=kor",
            str(root / "audio.m4a"),
        ]
    )
    _run(
        [
            FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(root / "small.mp4"),
        ]
    )
    return root


def write_catalog(root: Path, media: Path) -> Path:
    catalog = {
        "fixH264aacA": {"title": "Fixture H264", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4"), "live_status": "not_live"},
        "fixPort180A": {"title": "세로 영상", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "portrait.mp4")},
        "fixVP9opusA": {"title": "Fixture VP9", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "vp9.webm")},
        "fixAudioAAA": {"title": "Audio only", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "audio.m4a")},
        "fixSleepAAA": {"title": "Slow", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4"), "sleep_seconds": 2},
        "fix403jobAA": {"title": "Refresh", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4"), "job_script": ["HTTP_403", "ok"]},
        "fix429rateA": {"title": "Limited", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4"), "probe_script": ["SOURCE_RATE_LIMITED"]},
        "fixLiveVidA": {"title": "Live", "channel": "Fixture Lab", "live_status": "is_live", "duration": None},
        "fixEmptyHkA": {"title": "Empty", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4"), "test_hook": "empty"},
        "fixTextHkAA": {"title": "Text", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4"), "test_hook": "text"},
        "fixChangedA": {"title": "Change me", "channel": "Fixture Lab", "duration": 1.0, "file": str(media / "h264.mp4")},
        "fixHdrMetaA": {
            "title": "HDR",
            "channel": "Fixture Lab",
            "duration": 10,
            "live_status": "not_live",
            "streams": [
                {
                    "kind": "muxed",
                    "vcodec": "vp9",
                    "acodec": "opus",
                    "width": 1920,
                    "height": 1080,
                    "fps": 24,
                    "pix_fmt": "yuv420p10le",
                    "bit_depth": 10,
                    "dynamic_range": "hdr",
                    "color_transfer": "smpte2084",
                    "language": "en",
                    "role": "original",
                }
            ],
        },
        "PLFIXTURE1": {
            "entries": [
                {"position": index + 1, "video_id": f"fix{index:07d}A"[:11], "title": f"Item {index}", "available": index != 3, "reason": None if index != 3 else "private", "canonical_url": None}
                for index in range(25)
            ]
        },
    }
    # Keep video ids at 11 characters for the synthetic playlist rows.
    for index, entry in enumerate(catalog["PLFIXTURE1"]["entries"]):
        entry["video_id"] = f"p{index:09d}A"[:11]
        if entry["available"]:
            entry["canonical_url"] = f"https://www.youtube.com/watch?v={entry['video_id']}"
    path = root / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


@pytest.fixture
def settings(tmp_path, media_root, monkeypatch):
    catalog = write_catalog(tmp_path, media_root)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDIA_ADAPTER", "fixture")
    monkeypatch.setenv("ALLOW_FIXTURE_URLS", "1")
    monkeypatch.setenv("FIXTURE_CATALOG", str(catalog))
    monkeypatch.setenv("ALLOW_HTTP_BOOTSTRAP", "1")
    monkeypatch.setenv("ALLOW_TEST_HOOKS", "1")
    monkeypatch.setenv("LOCAL_HTTP", "1")
    monkeypatch.setenv("FFMPEG_PATH", FFMPEG)
    monkeypatch.setenv("FFPROBE_PATH", FFPROBE)
    monkeypatch.setenv("DENO_PATH", DENO)
    monkeypatch.setenv("MIN_FREE_BYTES", "0")
    monkeypatch.setenv("SSE_HEARTBEAT_SECONDS", "0.3")
    cfg = load_settings()
    return cfg


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


@pytest.fixture
def api(client, settings):
    return Api(client, settings)


class Api:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings
        self.csrf = None
        self.password = PASSWORD

    def headers(self, csrf: bool = True) -> dict[str, str]:
        headers = {
            "Origin": "http://127.0.0.1:8000",
            "X-Requested-With": "seorap",
            "Content-Type": "application/json",
            "X-Locale": "en",
        }
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        return headers

    def bootstrap(self) -> None:
        response = self.client.post("/api/v1/auth/bootstrap", json={"password": self.password}, headers=self.headers(False))
        assert response.status_code == 200, response.text

    def login(self) -> None:
        response = self.client.post("/api/v1/auth/login", json={"password": self.password}, headers=self.headers(False))
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]

    def ready(self) -> None:
        conn = connect(self.settings)
        try:
            if not operator_exists(conn):
                self.bootstrap()
            else:
                set_password(conn, self.password)
        finally:
            conn.close()
        self.login()

    def analyze(self, video_id: str = "fixH264aacA"):
        response = self.client.post(
            "/api/v1/analyses",
            json={"url": f"https://www.youtube.com/watch?v={video_id}"},
            headers=self.headers(),
        )
        assert response.status_code == 200, response.text
        return response.json()

    def create(self, analysis: dict, *, kind: str | None = None, choice_id: str | None = None, key: str = "idem-key-0001", keep: bool = False, consent: bool = False):
        choice = choice_id
        if choice is None:
            matches = [item for item in analysis["choices"] if item["kind"] == (kind or "mp4")]
            assert matches, analysis["choices"]
            preferred = [item for item in matches if item.get("is_default")]
            choice = (preferred or matches)[0]["choice_id"]
        response = self.client.post(
            "/api/v1/jobs",
            json={
                "analysis_id": analysis["analysis_id"],
                "choice_id": choice,
                "keep_on_server": keep,
                "conversion_consent": consent,
            },
            headers={**self.headers(), "Idempotency-Key": key},
        )
        return response
