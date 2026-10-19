#!/usr/bin/env python3
"""Linux Grok preview only; Compose owns its independent process lifecycle."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def http_ready(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=1) as response:
            return response.status == 200 and bool(response.read(256))
    except (OSError, ValueError):
        return False


def worker_state(data: Path) -> str:
    """The exclusive lock is authoritative; a PID file alone never proves health."""
    with (data / "worker.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return "stopped"
        try:
            handle.seek(0)
            owner = int(handle.read().strip())
            with sqlite3.connect(f"file:{data / 'state' / 'app.db'}?mode=ro", uri=True, timeout=1) as conn:
                row = conn.execute("SELECT beat_at,pid FROM worker_heartbeat WHERE id=1").fetchone()
            command = Path(f"/proc/{owner}/cmdline").read_bytes().split(b"\0")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(row[0])).total_seconds() if row else 999
            if row and row[1] == owner and b"app.worker" in command and 0 <= age < 30:
                return "ready"
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pass
        return "degraded"


def owned_runner(record_path: Path) -> bool:
    try:
        record = json.loads(record_path.read_text())
        pid = int(record["pid"])
        ticks = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return record["start_ticks"] == ticks and str(ROOT / "scripts/run-logged.py").encode() in command
    except (OSError, ValueError, KeyError, IndexError):
        return False


def component_ready(name: str, url: str, data: Path) -> bool:
    return owned_runner(data / "state" / f"preview-{name}.json") and http_ready(url)


def ensure_components(states: dict[str, str], running, launch) -> None:
    """Recover components independently; never spawn over a live owner."""
    for name, state in states.items():
        if state == "stopped" and not running(name):
            launch(name)


def preview_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Personal preview opens directly; an explicit protected profile is retained."""
    env = dict(os.environ if source is None else source)
    env.setdefault("DATA_DIR", str(ROOT / "data"))
    env.setdefault("LOCAL_HTTP", "1")
    env.setdefault("REQUIRE_PASSWORD", "0")
    env.setdefault("ALLOW_HTTP_BOOTSTRAP", "0")
    env.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")
    env.setdefault("MEDIA_ADAPTER", "ytdlp")
    env.setdefault("DENO_DIR", str(Path(env["DATA_DIR"]) / "tmp" / "deno-cache"))
    env.setdefault("XDG_CACHE_HOME", str(Path(env["DATA_DIR"]) / "tmp" / "cache"))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(ROOT / "backend") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PATH"] = str(ROOT / ".venv/bin") + os.pathsep + env.get("PATH", "") + os.pathsep + str(ROOT / "bin")
    return env


def main() -> int:
    env = preview_environment()
    for name, binary in (("FFMPEG_PATH", "ffmpeg"), ("FFPROBE_PATH", "ffprobe"), ("DENO_PATH", "deno")):
        if not env.get(name):
            found = shutil.which(binary, path=env["PATH"])
            if not found:
                print(f"Missing {binary}; install it or set {name} to a verified executable.", file=sys.stderr)
                return 1
            env[name] = found
    data = Path(env["DATA_DIR"]).resolve()
    for directory in (data / "state", data / "tmp", data / "files", data / "logs"):
        directory.mkdir(parents=True, exist_ok=True)
    python = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable
    commands = {
        "api": [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        "worker": [python, "-m", "app.worker"],
        "web": ["npm", "run", "dev"],
    }
    with (data / "state" / "preview-start.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        states = {"worker": worker_state(data)}
        for name, url in (("api", "http://127.0.0.1:8000/healthz"), ("web", "http://127.0.0.1:8080/")):
            states[name] = ("ready" if owned_runner(data / "state" / f"preview-{name}.json") else "foreign") if http_ready(url) else "stopped"

        def launch(name):
            command = [python, str(ROOT / "scripts/run-logged.py"), "--log", str(data / "logs" / f"{name}.log"), "--pid", str(data / "state" / f"preview-{name}.json"), "--max-bytes", env.get("LOG_MAX_BYTES", "5242880"), "--", *commands[name]]
            subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

        ensure_components(states, lambda name: owned_runner(data / "state" / f"preview-{name}.json"), launch)
        foreign = [name for name, state in states.items() if state == "foreign"]
        if foreign:
            print("Preview cannot adopt an unowned listener: " + ", ".join(foreign) + ". Existing processes were preserved; stop only the intended service before using this profile.", file=sys.stderr)
            return 1
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if component_ready("api", "http://127.0.0.1:8000/healthz", data) and worker_state(data) == "ready" and component_ready("web", "http://127.0.0.1:8080/", data):
                print("Preview services: API, exclusive worker heartbeat and web are ready. Authentication follows explicit profile settings.")
                return 0
            time.sleep(0.5)
        print("Preview degraded: API, worker lock/heartbeat or web readiness failed. Inspect bounded data/logs; a live owner is never replaced automatically.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
