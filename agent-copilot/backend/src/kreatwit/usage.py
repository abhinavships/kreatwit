"""Per-member daily caps (questions, uploads) for the public server. No-op outside a workspace (local dev, tests)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from fastapi import HTTPException

from kreatwit import orgs, workspace
from kreatwit.settings import settings

_LOCK = threading.Lock()
_CON: sqlite3.Connection | None = None


def _con() -> sqlite3.Connection:
    global _CON
    if _CON is None:
        _CON = sqlite3.connect(settings.db_path.with_name("usage.sqlite"), check_same_thread=False)
        _CON.execute("CREATE TABLE IF NOT EXISTS usage (ws TEXT, day TEXT, kind TEXT, n INTEGER, PRIMARY KEY (ws, day, kind))")
    return _CON


def take(kind: str, limit: int) -> None:
    """Count one `kind` for today's account; 429 once the daily limit is reached (UTC days)."""
    ws, m = workspace.CURRENT.get(), orgs.MEMBER.get()
    if not ws:
        return
    ws = f"{ws}/{m['user_id']}" if m else ws
    day = datetime.now(timezone.utc).date().isoformat()
    with _LOCK:
        c = _con()
        n = (c.execute("SELECT n FROM usage WHERE ws=? AND day=? AND kind=?", [ws, day, kind]).fetchone() or [0])[0]
        if n >= limit:
            raise HTTPException(429, f"daily limit reached ({limit} {kind} per day); it resets at 00:00 UTC")
        c.execute("INSERT INTO usage VALUES (?,?,?,1) ON CONFLICT (ws, day, kind) DO UPDATE SET n = n + 1", [ws, day, kind])
        c.commit()
