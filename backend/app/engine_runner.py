"""Supervise one engine subprocess group."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from queue import Empty, Queue
from typing import Any

from app.config import Settings


def execute(
    payload: dict[str, Any],
    settings: Settings,
    *,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    deadline_seconds: int = 60,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["YTDLP_NO_PLUGINS"] = "1"
    env["PYTHONPATH"] = str(_backend_root())
    env["DATA_DIR"] = str(settings.data_dir)
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.engine.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(json.dumps(payload).encode("utf-8"))
    proc.stdin.close()
    stderr = bytearray()

    def drain_stderr() -> None:
        while True:
            chunk = proc.stderr.read(4096)
            if not chunk:
                break
            stderr.extend(chunk)
            if len(stderr) > 65536:
                del stderr[:-32768]

    threading.Thread(target=drain_stderr, daemon=True).start()
    lines: Queue[bytes | None] = Queue()

    def drain_stdout() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=drain_stdout, daemon=True).start()
    started = time.monotonic()
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    while True:
        if should_cancel and should_cancel():
            _terminate(proc)
            return {"status": "cancelled", "stderr": _safe_text(stderr)}
        if time.monotonic() - started > deadline_seconds:
            _terminate(proc)
            return {"status": "timeout", "stderr": _safe_text(stderr)}
        try:
            line = lines.get(timeout=0.2)
        except Empty:
            if proc.poll() is not None and lines.empty():
                break
            continue
        if line is None:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text or len(text) > 1_000_000:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "progress" and on_event:
            on_event(event)
        elif event.get("type") == "result":
            result = event
        elif event.get("type") == "error":
            error = event
    try:
        code = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate(proc)
        code = proc.wait(timeout=5)
    if should_cancel and should_cancel():
        return {"status": "cancelled", "stderr": _safe_text(stderr)}
    if error:
        return {"status": "error", "error": error, "returncode": code, "stderr": _safe_text(stderr)}
    if result and result.get("ok") and code == 0:
        return {"status": "ok", "result": result, "returncode": 0, "stderr": _safe_text(stderr)}
    return {"status": "error", "error": {"code": "ENGINE_ERROR", "message": "engine failed", "retryable": True}, "returncode": code, "stderr": _safe_text(stderr)}


def _terminate(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    proc.wait(timeout=5)


def _safe_text(buf: bytearray) -> str:
    text = buf.decode("utf-8", errors="replace")
    return text[-4000:]


def _backend_root():
    return __import__("pathlib").Path(__file__).resolve().parent.parent
