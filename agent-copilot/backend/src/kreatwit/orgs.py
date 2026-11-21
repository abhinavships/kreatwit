"""Organizations: the unit of data. An org owns one workspace (DuckDB file + upload folder); its members share it.

Control plane in SQLite beside the template db (orgs.sqlite): orgs, members, invites. Supabase owns identities;
a member row maps a Supabase user id to an org, a role and a principal (the user id the data layer records as the
author of corrections, notes and chats). Membership is read on every request, so a role change or removal takes
effect immediately, not when the cookie expires.

Roles: owner > admin > member > viewer.
  viewer  ask questions, see the org's data
  member  + upload data, correct records, resolve disputes
  admin   + invite, remove and re-role members (not owners)
  owner   + make other owners
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import HTTPException

from kreatwit import workspace
from kreatwit.settings import settings

ROLES = ("viewer", "member", "admin", "owner")
MEMBER: ContextVar[dict | None] = ContextVar("kreatwit_member", default=None)  # set by the auth middleware

_LOCK = threading.Lock()
_CON: sqlite3.Connection | None = None
SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (org_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members (org_id TEXT NOT NULL REFERENCES orgs, sb_uid TEXT PRIMARY KEY, email TEXT NOT NULL,
  name TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', role TEXT NOT NULL, user_id TEXT NOT NULL, joined_at TEXT NOT NULL,
  UNIQUE (org_id, user_id));
CREATE TABLE IF NOT EXISTS invites (org_id TEXT NOT NULL REFERENCES orgs, email TEXT NOT NULL, role TEXT NOT NULL,
  invited_by TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (org_id, email));
"""
# ponytail: one org per account (sb_uid is the members key); make (org_id, sb_uid) the key + an org switcher for many


def _con() -> sqlite3.Connection:
    global _CON
    if _CON is None:
        _CON = sqlite3.connect(settings.db_path.with_name("orgs.sqlite"), check_same_thread=False)
        _CON.row_factory = sqlite3.Row
        _CON.executescript(SCHEMA)
    return _CON


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(sql: str, args=()) -> list[dict]:
    with _LOCK:
        return [dict(r) for r in _con().execute(sql, args).fetchall()]


def _w(sql: str, args=()) -> int:
    with _LOCK:
        c = _con()
        n = c.execute(sql, args).rowcount
        c.commit()
        return n


def rank(role: str) -> int:
    return ROLES.index(role)


def member(sb_uid: str) -> dict | None:
    r = _q("""SELECT m.*, o.name AS org_name FROM members m JOIN orgs o USING (org_id) WHERE m.sb_uid=?""", [sb_uid])
    return r[0] if r else None


def require(role: str) -> dict | None:
    """403 unless the current member has at least `role`. No-op when sign-in is off (local dev: you are everyone)."""
    m = MEMBER.get()
    if m and rank(m["role"]) < rank(role):
        raise HTTPException(403, f"needs the {role} role; you are {m['role']}")
    return m


def _sync(m: dict) -> None:
    """Mirror the member into the org database's users table, so answers name them like any other person."""
    db = workspace.get(m["org_id"])
    db.run("DELETE FROM users WHERE dataset_id=? AND user_id=?", [settings.active_dataset, m["user_id"]])
    db.run("INSERT INTO users (dataset_id, user_id, name, role, team_id) VALUES (?,?,?,?,NULL)",
           [settings.active_dataset, m["user_id"], m["name"], m["title"] or m["role"]])


def _join(org_id: str, sb_uid: str, email: str, name: str, role: str, title: str = "") -> dict:
    user_id = "M-" + sb_uid.replace("-", "")[:10].upper()  # cannot collide with the dataset's U-### people
    _w("INSERT INTO members VALUES (?,?,?,?,?,?,?,?)", [org_id, sb_uid, email.lower(), name, title, role, user_id, _now()])
    m = member(sb_uid)
    _sync(m)
    return m


def create(sb_uid: str, email: str, name: str, org_name: str, title: str = "") -> dict:
    if member(sb_uid):
        raise HTTPException(409, "you already belong to an organization")
    org_id = str(uuid.uuid4())
    _w("INSERT INTO orgs VALUES (?,?,?)", [org_id, org_name.strip(), _now()])
    return _join(org_id, sb_uid, email, name.strip(), "owner", title.strip())


def accept_invite(sb_uid: str, email: str) -> dict | None:
    """On sign-in: an account without an org joins the org that invited its email (oldest invite wins)."""
    inv = _q("SELECT * FROM invites WHERE email=? ORDER BY created_at LIMIT 1", [email.lower()])
    if not inv or member(sb_uid):
        return None
    i = inv[0]
    _w("DELETE FROM invites WHERE email=?", [email.lower()])
    return _join(i["org_id"], sb_uid, email, email.split("@")[0], i["role"])


def pending_invite(email: str) -> dict | None:
    r = _q("SELECT i.role, o.name AS org_name FROM invites i JOIN orgs o USING (org_id) WHERE i.email=?", [email.lower()])
    return r[0] if r else None


def members(org_id: str) -> list[dict]:
    return _q("SELECT user_id, email, name, title, role, joined_at FROM members WHERE org_id=? ORDER BY joined_at", [org_id])


def invites(org_id: str) -> list[dict]:
    return _q("SELECT email, role, invited_by, created_at FROM invites WHERE org_id=? ORDER BY created_at", [org_id])


def _check_role(me: dict, role: str) -> None:
    if role not in ROLES:
        raise HTTPException(400, f"role must be one of {', '.join(ROLES)}")
    if role == "owner" and me["role"] != "owner":
        raise HTTPException(403, "only an owner can make owners")


def invite(me: dict, email: str, role: str) -> None:
    _check_role(me, role)
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "not an email address")
    if _q("SELECT 1 FROM members WHERE email=?", [email]):
        raise HTTPException(409, f"{email} already belongs to an organization")
    _w("INSERT OR REPLACE INTO invites VALUES (?,?,?,?,?)", [me["org_id"], email, role, me["email"], _now()])


def revoke(me: dict, email: str) -> None:
    _w("DELETE FROM invites WHERE org_id=? AND email=?", [me["org_id"], email.strip().lower()])


def _target(me: dict, user_id: str) -> dict:
    t = _q("SELECT * FROM members WHERE org_id=? AND user_id=?", [me["org_id"], user_id])
    if not t:
        raise HTTPException(404, "no such member")
    if t[0]["role"] == "owner" and me["role"] != "owner":
        raise HTTPException(403, "only an owner can change an owner")
    return t[0]


def _owners_left(org_id: str, without: str) -> int:
    return _q("SELECT count(*) n FROM members WHERE org_id=? AND role='owner' AND user_id<>?", [org_id, without])[0]["n"]


def set_role(me: dict, user_id: str, role: str) -> None:
    _check_role(me, role)
    t = _target(me, user_id)
    if t["role"] == "owner" and role != "owner" and not _owners_left(me["org_id"], user_id):
        raise HTTPException(409, "an organization needs at least one owner")
    _w("UPDATE members SET role=? WHERE org_id=? AND user_id=?", [role, me["org_id"], user_id])


def remove(me: dict, user_id: str) -> None:
    """Removes access only: what they uploaded and corrected stays with the org, attributed to them."""
    t = _target(me, user_id) if user_id != me["user_id"] else me  # anyone may leave
    if t["role"] == "owner" and not _owners_left(me["org_id"], user_id):
        raise HTTPException(409, "an organization needs at least one owner")
    _w("DELETE FROM members WHERE org_id=? AND user_id=?", [me["org_id"], user_id])


def update_profile(me: dict, name: str, title: str) -> dict:
    _w("UPDATE members SET name=?, title=? WHERE sb_uid=?", [name.strip() or me["name"], title.strip(), me["sb_uid"]])
    m = member(me["sb_uid"])
    _sync(m)
    return m


def rename(me: dict, name: str) -> None:
    _w("UPDATE orgs SET name=? WHERE org_id=?", [name.strip(), me["org_id"]])
