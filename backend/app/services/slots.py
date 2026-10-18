"""Cross-process analysis permits stored in SQLite."""

from __future__ import annotations

import secrets
from datetime import timedelta

from app.config import Settings
from app.db import connect, transaction, utc_iso, utc_now


def acquire_slot(settings: Settings, owner: str) -> str | None:
    conn = connect(settings)
    try:
        now = utc_now()
        with transaction(conn):
            conn.execute("DELETE FROM analysis_slots WHERE expires_at < ?", (utc_iso(now),))
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
