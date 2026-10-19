"""Cross-process analysis permits stored in SQLite."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from app.config import Settings
from app.db import connect, transaction, utc_iso, utc_now
from app.errors import AppError


def acquire_slot(settings: Settings, owner: str) -> str | None:
    conn = connect(settings)
    try:
        now = utc_now()
        with transaction(conn):
            cooldown = conn.execute("SELECT until_at FROM provider_cooldown WHERE provider = 'youtube'").fetchone()
            if cooldown:
                remaining = (datetime.fromisoformat(cooldown["until_at"]) - now).total_seconds()
                if remaining > 0:
                    raise AppError("SOURCE_RATE_LIMITED", 429, retryable=True, retry_after=int(remaining) + 1)
            conn.execute("DELETE FROM analysis_slots WHERE expires_at <= ?", (utc_iso(now),))
            count = conn.execute("SELECT COUNT(*) AS c FROM analysis_slots").fetchone()["c"]
            if count >= settings.analysis_concurrency:
                return None
            slot_id = secrets.token_hex(8)
            conn.execute(
                "INSERT INTO analysis_slots (id, owner, expires_at) VALUES (?, ?, ?)",
                (
                    slot_id,
                    owner,
                    utc_iso(now + timedelta(seconds=settings.analysis_deadline_seconds + 15)),
                ),
            )
            return slot_id
    finally:
        conn.close()


def release_slot(settings: Settings, slot_id: str | None) -> None:
    if not slot_id:
        return
    conn = connect(settings)
    try:
        conn.execute("DELETE FROM analysis_slots WHERE id = ?", (slot_id,))
    finally:
        conn.close()


def renew_slot(settings: Settings, slot_id: str) -> bool:
    """Only the live owner may extend a still-current bounded metadata permit."""
    conn = connect(settings)
    try:
        now = utc_now()
        return conn.execute(
            "UPDATE analysis_slots SET expires_at = ? WHERE id = ? AND expires_at > ?",
            (utc_iso(now + timedelta(seconds=settings.analysis_deadline_seconds + 15)), slot_id, utc_iso(now)),
        ).rowcount == 1
    finally:
        conn.close()
