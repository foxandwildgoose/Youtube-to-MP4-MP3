#!/usr/bin/env python3
"""Own one preview process group and collect bounded rotating output."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys


def start_ticks(pid: int) -> str | None:
    try:
        # The parenthesized comm field may contain spaces.
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def append_bounded(path: Path, data: bytes, maximum: int, backups: int = 2) -> None:
    """Bound current and every backup, including an oversized preexisting log."""
    if maximum < 1 or backups < 1:
        raise ValueError("log size and backup count must be positive")
    path.parent.mkdir(parents=True, exist_ok=True)
    for candidate in [path, *(Path(f"{path}.{i}") for i in range(1, backups + 1))]:
        if candidate.exists() and candidate.stat().st_size > maximum:
            with candidate.open("rb+") as stream:
                stream.seek(-maximum, os.SEEK_END)
                tail = stream.read()
                stream.seek(0)
                stream.write(tail)
                stream.truncate()
    while data:
        size = path.stat().st_size if path.exists() else 0
        if size >= maximum:
            Path(f"{path}.{backups}").unlink(missing_ok=True)
            for i in range(backups - 1, 0, -1):
                old = Path(f"{path}.{i}")
                if old.exists():
                    old.replace(Path(f"{path}.{i + 1}"))
            path.replace(Path(f"{path}.1"))
            size = 0
        part, data = data[: maximum - size], data[maximum - size :]
        with path.open("ab") as stream:
            stream.write(part)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--pid", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.max_bytes < 1:
        parser.error("a command and positive log size are required")
    child = None
    selector = None
    stopping = False

    def forward(signum, _frame):
        nonlocal stopping
        stopping = True
        if child is not None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, forward)
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        # Every post-spawn operation belongs to this cleanup lifetime, including
        # state-file creation and selector setup when storage is unavailable.
        if stopping:
            forward(signal.SIGTERM, None)
        args.pid.parent.mkdir(parents=True, exist_ok=True)
        args.pid.write_text(json.dumps({"pid": os.getpid(), "start_ticks": start_ticks(os.getpid()), "child_pid": child.pid}))
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        while selector.get_map():
            for key, _ in selector.select(timeout=0.5):
                data = os.read(key.fd, 8192)
                if data:
                    append_bounded(args.log, data, args.max_bytes)
                else:
                    selector.unregister(key.fileobj)
            if stopping and child.poll() is None:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        if selector is not None:
            selector.close()
        # A wrapper setup failure must not orphan the process group it owns.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if child.poll() is None:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        child.stdout.close()
        try:
            record = json.loads(args.pid.read_text())
            if record.get("pid") == os.getpid():
                args.pid.unlink()
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
