"""Password hashing, sessions, CSRF, and host checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import timedelta
from urllib.parse import urlsplit

from app.config import Settings
from app.db import transaction, utc_iso, utc_now
from app.errors import AppError


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, dk_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def operator_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT id FROM operator WHERE id = 1").fetchone()
    return row is not None


def set_password(conn: sqlite3.Connection, password: str) -> None:
    if len(password) < 10:
        raise AppError("BAD_REQUEST", 400, extra={"message": "Password must be at least 10 characters.", "action": "Choose a longer password."})
    now = utc_iso()
    digest = hash_password(password)
    with transaction(conn):
        if operator_exists(conn):
            conn.execute(
                "UPDATE operator SET password_hash = ?, updated_at = ? WHERE id = 1",
                (digest, now),
            )
        else:
            conn.execute(
                "INSERT INTO operator (id, password_hash, created_at, updated_at) VALUES (1, ?, ?, ?)",
                (digest, now, now),
            )
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE revoked_at IS NULL", (now,))


def revoke_all_sessions(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE sessions SET revoked_at = ? WHERE revoked_at IS NULL", (utc_iso(),))


def hostname_of(host_header: str) -> str:
    value = (host_header or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else value
    return value.split(":", 1)[0]


def host_allowed(settings: Settings, host_header: str | None) -> bool:
    if not host_header:
        return False
    return hostname_of(host_header) in settings.allowed_hosts


def origin_allowed(settings: Settings, origin: str | None, host_header: str | None) -> bool:
    if not host_allowed(settings, host_header):
        return False
    if not origin:
        return False
    parts = urlsplit(origin)
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.username or parts.password:
        return False
    origin_host = parts.hostname or ""
    if origin_host.lower() not in settings.allowed_hosts:
        return False
    # Exact host the browser used, including port when present.
    expected = host_header.strip().lower() if host_header else ""
    return parts.netloc.lower() == expected


def _prune_attempts(conn: sqlite3.Connection) -> None:
    cutoff = utc_iso(utc_now() - timedelta(minutes=15))
    conn.execute("DELETE FROM login_attempts WHERE at < ?", (cutoff,))


def login_throttled(conn: sqlite3.Connection, ip: str) -> int | None:
    _prune_attempts(conn)
    cutoff = utc_iso(utc_now() - timedelta(minutes=15))
    row = conn.execute(
        "SELECT COUNT(*) AS c, MIN(at) AS first_at FROM login_attempts WHERE ip = ? AND success = 0 AND at >= ?",
        (ip, cutoff),
    ).fetchone()
    if row and row["c"] >= 5:
        return 60
    return None


def record_login(conn: sqlite3.Connection, ip: str, success: bool) -> None:
    conn.execute(
        "INSERT INTO login_attempts (ip, at, success) VALUES (?, ?, ?)",
        (ip, utc_iso(), 1 if success else 0),
    )


def create_session(conn: sqlite3.Connection, settings: Settings) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    sid = secrets.token_hex(16)
    now = utc_now()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO sessions (id, token_hash, csrf_secret, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sid, hash_token(token), csrf, utc_iso(now), utc_iso(now + timedelta(seconds=settings.session_ttl_seconds)), utc_iso(now)),
        )
    return sid, token, csrf


def session_from_token(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (hash_token(token),)).fetchone()
    if row is None or row["revoked_at"]:
        return None
    if row["expires_at"] <= utc_iso():
        return None
    return row


def touch_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (utc_iso(), session_id))


def revoke_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (utc_iso(), session_id))


def cookie_kwargs(settings: Settings) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": not settings.local_http,
        "path": "/",
        "max_age": settings.session_ttl_seconds,
    }
