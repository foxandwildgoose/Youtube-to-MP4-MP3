"""Own one engine process group, including silent descendants and failed callbacks."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any

from app.config import Settings
from app.errors import AppError

TERMINATE_GRACE_SECONDS = 2.0
_ACTIVE: set[subprocess.Popen] = set()
_ACTIVE_LOCK = threading.Lock()


def execute(
    payload: dict[str, Any],
    settings: Settings,
    *,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    watchdog: Callable[[], None] | None = None,
    deadline_seconds: int = 60,
) -> dict[str, Any]:
    """Callbacks may raise; the owned group is still stopped before that escapes.

    The bounded watchdog runs every 200 ms even when yt-dlp/FFmpeg is silent.
    Reader queues retain a bounded number of events and stderr a bounded tail.
    """
    env = os.environ.copy()
    env["YTDLP_NO_PLUGINS"] = "1"
    env["PYTHONPATH"] = str(_backend_root())
    env["DATA_DIR"] = str(settings.data_dir)
    _enable_subreaper()
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.engine.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )
    stderr = bytearray()
    lines: Queue[bytes | None] = Queue(maxsize=128)
    finished = threading.Event()
    stdout_done = threading.Event()
    leader_finished = False
    readers: list[threading.Thread] = []
    marker: Path | None = None
    with _ACTIVE_LOCK:
        _ACTIVE.add(proc)
    try:
        marker = _record_engine(settings, proc)
        assert proc.stdin and proc.stdout and proc.stderr

        def enqueue(line: bytes | None) -> None:
            while not finished.is_set():
                try:
                    lines.put(line, timeout=0.1)
                    return
                except Full:
                    continue

        def drain_stderr() -> None:
            assert proc.stderr
            while not finished.is_set():
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                stderr.extend(chunk)
                if len(stderr) > 65536:
                    del stderr[:-32768]

        def drain_stdout() -> None:
            assert proc.stdout
            try:
                while not finished.is_set():
                    line = proc.stdout.readline(1_000_001)
                    if not line:
                        break
                    # A broken engine cannot allocate an unlimited line.
                    if len(line) <= 1_000_000 and line.endswith(b"\n"):
                        enqueue(line)
            finally:
                enqueue(None)
                stdout_done.set()

        for target in (drain_stderr, drain_stdout):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            readers.append(thread)
        proc.stdin.write(json.dumps(payload).encode("utf-8"))
        proc.stdin.close()
        started = time.monotonic()
        result: dict[str, Any] | None = None
        error: dict[str, Any] | None = None
        while True:
            if should_cancel and should_cancel():
                return {"status": "cancelled", "stderr": _safe_text(stderr)}
            if time.monotonic() - started > deadline_seconds:
                return {"status": "timeout", "stderr": _safe_text(stderr)}
            if watchdog:
                try:
                    watchdog()
                except AppError as exc:
                    return {"status": "error", "error": {"code": exc.code, "retryable": exc.retryable}, "stderr": _safe_text(stderr)}
            try:
                line = lines.get(timeout=0.2)
            except Empty:
                if proc.poll() is not None:
                    if not leader_finished:
                        # Stop inherited-pipe descendants so stdout can reach
                        # EOF, then consume every event before that sentinel.
                        _terminate(proc)
                        leader_finished = True
                    if stdout_done.is_set() and lines.empty():
                        break
                continue
            if line is None:
                # stdout EOF is not proof the child or its descendants stopped.
                if proc.poll() is not None:
                    break
                continue
            try:
                event = json.loads(line.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "progress" and on_event:
                on_event(event)
            elif event.get("type") == "result":
                result = event
            elif event.get("type") == "error":
                error = event
        code = proc.wait(timeout=1)
        if should_cancel and should_cancel():
            return {"status": "cancelled", "stderr": _safe_text(stderr)}
        if watchdog:
            watchdog()
        if error:
            return {"status": "error", "error": error, "returncode": code, "stderr": _safe_text(stderr)}
        if result and result.get("ok") and code == 0:
            return {"status": "ok", "result": result, "returncode": 0, "stderr": _safe_text(stderr)}
        return {"status": "error", "error": {"code": "ENGINE_ERROR", "message": "engine failed", "retryable": True}, "returncode": code, "stderr": _safe_text(stderr)}
    finally:
        # Always signal the group, even if the leader already exited: a child
        # may have forked FFmpeg or an inherited-pipe descendant.
        _terminate(proc)
        finished.set()
        for thread in readers:
            thread.join(timeout=1)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe:
                try:
                    pipe.close()
                except OSError:
                    pass
        with _ACTIVE_LOCK:
            _ACTIVE.discard(proc)
        if marker:
            marker.unlink(missing_ok=True)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _terminate(proc: subprocess.Popen) -> None:
    _terminate_group(proc.pid, proc.poll)
    try:
        proc.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=TERMINATE_GRACE_SECONDS)
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while _group_alive(proc.pid) and time.monotonic() < deadline:
        _reap_group(proc.pid)
        time.sleep(0.02)
    _reap_group(proc.pid)


def _terminate_group(pgid: int, reap_leader: Callable | None = None) -> None:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while _group_alive(pgid) and time.monotonic() < deadline:
        if reap_leader:
            reap_leader()
        _reap_group(pgid, exclude_leader=bool(reap_leader))
        time.sleep(0.02)
    if _group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass



def _enable_subreaper() -> None:
    # Linux is the supported Compose platform. Reparent grandchildren here so
    # we can reap them instead of relying on an arbitrary container PID 1.
    if sys.platform == "linux":
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)


def _reap_group(pgid: int, *, exclude_leader: bool = False) -> None:
    if exclude_leader:
        # Do not consume Popen's direct-child wait status.
        return
    while True:
        try:
            pid, _ = os.waitpid(-pgid, os.WNOHANG)
            if pid == 0:
                return
        except ChildProcessError:
            return


def stop_owned_engines() -> None:
    with _ACTIVE_LOCK:
        active = list(_ACTIVE)
    for proc in active:
        _terminate(proc)


def _process_start(pid: int) -> int | None:
    try:
        # /proc field 22; rsplit handles spaces and parentheses in comm.
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _namespace_id() -> str:
    # App and worker containers share a volume, but not a PID namespace.
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return f"process:{os.getpid()}"


def _marker_path(settings: Settings, pid: int) -> Path:
    identity = "".join(character for character in _namespace_id() if character.isalnum())
    return settings.db_path.parent / f"engine-{identity}-{pid}.json"


def _record_engine(settings: Settings, proc: subprocess.Popen) -> Path:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    marker = _marker_path(settings, proc.pid)
    marker.write_text(json.dumps({"pid": proc.pid, "start": _process_start(proc.pid),
                                 "owner_pid": os.getpid(), "owner_start": _process_start(os.getpid()),
                                 "namespace": _namespace_id()}), encoding="utf-8")
    return marker


def cleanup_stale_engines(settings: Settings) -> None:
    """After exclusive worker lock: stop old groups before removing workspaces.

    A Linux process birth identifier prevents PID-reuse accidents. If the
    leader has exited, inspect group members rather than trusting a bare PID.
    """
    for marker in settings.db_path.parent.glob("engine-*.json"):
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if data.get("namespace") != _namespace_id():
                # Never interpret another container's numeric PIDs locally.
                # Container termination owns those processes. Only stale
                # metadata beyond every configured execution window expires.
                age = time.time() - marker.stat().st_mtime
                if age > max(86400, settings.active_job_deadline_seconds + 3600):
                    marker.unlink(missing_ok=True)
                continue
            pid, born = int(data["pid"]), data.get("start")
            owner_pid, owner_start = data.get("owner_pid"), data.get("owner_start")
            # API analysis has its own live owner in the same data volume.
            if owner_pid and owner_start and _process_start(int(owner_pid)) == owner_start:
                continue
            valid = born is not None and _process_start(pid) == born
            if not valid and born is not None and _process_start(pid) is None:
                for member in Path("/proc").iterdir():
                    if not member.name.isdecimal():
                        continue
                    try:
                        fields = (member / "stat").read_text().rsplit(")", 1)[1].split()
                        if int(fields[2]) == pid and int(fields[19]) >= int(born):
                            valid = True
                            break
                    except (OSError, ValueError, IndexError):
                        continue
            if valid:
                _terminate_group(pid)
            marker.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError):
            # Corrupt ownership evidence is not authority to kill a process.
            marker.unlink(missing_ok=True)


def _safe_text(buf: bytearray) -> str:
    return buf.decode("utf-8", errors="replace")[-4000:]


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent
