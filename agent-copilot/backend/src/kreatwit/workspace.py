"""Workspaces: every organization (kreatwit.orgs) gets its own DuckDB file, so one org can never read another's data.

Isolation is physical, not a WHERE clause: the agent's SQL, the caches, chat handles and uploads all live in the
org's file and folder. Each workspace connection is sandboxed (no file access outside its own upload folder,
no ATTACH), which also closes the escape hatches a regex SQL guard misses (read_ndjson_auto, sqlite_scan, ...).

Off when no workspace is set (local dev, tests, evals): everything uses settings.db_path as before.
A new workspace starts as a copy of a template: the sample dataset (settings.db_path, built at boot) or, by default,
the same schema with no rows (empty.duckdb, derived from it on first use), so an org only sees what it uploads.
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


SAMPLE_ONLY = ("areas", "assertions", "docs", "dq_flags", "episodes", "equipment", "handles", "inspections", "kb_chunks",
               "kb_vectors", "maintenance", "notes", "reg_events", "report_facts", "reports", "skill_runs", "teams", "users",
               "wells")  # every table holding sample rows; rules, skills and type_inherits are product config


def _empty_template() -> Path:
    import duckdb
    out = settings.db_path.with_name("empty.duckdb")
    if not out.exists():
        tmp = out.with_suffix(".tmp")
        shutil.copyfile(settings.db_path, tmp)
        con = duckdb.connect(str(tmp))
        try:
            have = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name='main'").fetchall()}
            for t in SAMPLE_ONLY:  # some tables are created lazily, on first use
                if t in have:
                    con.execute(f"DELETE FROM {t}")
            con.execute("LOAD fts")
            con.execute("PRAGMA create_fts_index('kb_chunks', 'cid', 'title', 'text', stemmer='porter', "
                        "stopwords='english', ignore='(\\.|[^a-z0-9])+', strip_accents=1, lower=1, overwrite=1)")
            con.execute("CHECKPOINT")
        finally:
            con.close()
        tmp.rename(out)
    return out


def get(ws: str, sample: bool = False):
    """The workspace's Db, created on first use from the empty template (or the sample one). LRU ones are closed."""
    from kreatwit.tools.core import Db

    with _LOCK:
        if ws in _OPEN:
            _OPEN.move_to_end(ws)
            return _OPEN[ws]
        path = db_file(ws)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            src = settings.db_path if sample else _empty_template()  # the sample template is never opened in-process
            shutil.copyfile(src, path.with_suffix(".tmp"))
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
