"""Workspaces: every organization (kreatwit.orgs) gets its own DuckDB file, so one org can never read another's data.

Isolation is physical, not a WHERE clause: the agent's SQL, the caches, chat handles and uploads all live in the
org's file and folder. Each workspace connection is sandboxed (no file access outside its own upload folder,
no ATTACH), which also closes the escape hatches a regex SQL guard misses (read_ndjson_auto, sqlite_scan, ...).

Off when no workspace is set (local dev, tests, evals): everything uses settings.db_path as before.
A new workspace starts as a copy of the template database (settings.db_path, built from the sample dataset at boot).
"""

from __future__ import annotations

import re
import shutil
import threading
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path

from kreatwit.settings import ROOT, settings

CURRENT: ContextVar[str | None] = ContextVar("kreatwit_workspace", default=None)
ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")  # org ids (and Supabase user ids)
OPEN_MAX = 8  # open workspace databases kept in memory
MEMORY_LIMIT = "200MB"  # per workspace connection; the machine has 1 GB

_LOCK = threading.Lock()
_OPEN: OrderedDict[str, object] = OrderedDict()  # ws id -> Db, least recently used first


def check(ws: str) -> str:
    if not ID_RE.match(ws or ""):
        raise ValueError(f"bad workspace id {ws!r}")
    return ws


def db_file(ws: str) -> Path:
    return settings.db_path.parent / "ws" / check(ws) / "kreatwit.duckdb"


def uploads_dir(ws: str | None = None) -> Path:
    """Upload folder for a workspace (backend/uploads is a symlink to the volume in the image)."""
    ws = ws if ws is not None else CURRENT.get()
    base = ROOT / "backend" / "uploads"
    return base / check(ws) if ws else base


def get(ws: str):
    """The workspace's Db, created from the template on first use. Least recently used ones are closed."""
    from kreatwit.tools.core import Db

    with _LOCK:
        if ws in _OPEN:
            _OPEN.move_to_end(ws)
            return _OPEN[ws]
        path = db_file(ws)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(settings.db_path, path.with_suffix(".tmp"))  # the template is never opened in-process
            path.with_suffix(".tmp").rename(path)
        up = uploads_dir(ws)
        up.mkdir(parents=True, exist_ok=True)
        db = Db(path, sandbox=up)
        _OPEN[ws] = db
        # ponytail: closing the LRU one under load could cut a long turn short; raise OPEN_MAX or refcount if seen
        while len(_OPEN) > OPEN_MAX:
            _, old = _OPEN.popitem(last=False)
            old.close()
        return db
