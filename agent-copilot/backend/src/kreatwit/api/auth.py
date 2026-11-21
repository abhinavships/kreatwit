"""Accounts and sessions. Off unless AUTH_SECRET is set (local dev, tests); the Docker image refuses to start without it.

An account is an email + password mapped to one dataset user (the principal). The middleware is the only place identity
enters: it verifies the session cookie, then overwrites X-User-Id and ?principal=, so no endpoint trusts the client.

Accounts live in their own SQLite file because the API process holds the DuckDB lock, so the CLI can add users while
the server runs:  python -m kreatwit.api.auth add <email> <user_id> | list | remove <email>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from kreatwit.settings import settings

COOKIE = "kreatwit_session"
TTL = 7 * 24 * 3600
OPEN = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me"}
PROTECTED = ("/api/", "/mcp", "/skills-mcp")  # everything else is the static UI
MAX_FAILS, LOCK_S = 5, 15 * 60
# ponytail: lockout counters are in-process (fine for the single instance DuckDB allows); move to the store if scaled out
_FAILS: dict[str, tuple[int, float]] = {}

router = APIRouter(prefix="/api/auth")


def enabled() -> bool:
    return bool(settings.auth_secret)


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(settings.db_path.with_name("accounts.sqlite"))
    con.execute("CREATE TABLE IF NOT EXISTS accounts (email TEXT PRIMARY KEY, pw TEXT NOT NULL, user_id TEXT NOT NULL)")
    return con


def hash_pw(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    return salt.hex() + "$" + hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def check_pw(password: str, stored: str) -> bool:
    return hmac.compare_digest(hash_pw(password, bytes.fromhex(stored.split("$")[0])), stored)


_DUMMY = hash_pw("-")  # unknown emails cost the same as known ones


def _mac(body: str) -> str:
    return hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def sign(user_id: str, email: str, ttl: int = TTL) -> str:
    raw = json.dumps({"u": user_id, "e": email, "x": int(time.time()) + ttl}).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")  # no padding: "=" would make the cookie value quoted
    return f"{body}.{_mac(body)}"


def verify(token: str | None) -> dict | None:
    body, _, mac = (token or "").partition(".")
    if not mac or not hmac.compare_digest(_mac(body), mac):
        return None
    try:
        s = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    return s if s.get("x", 0) > time.time() else None


def _cookie(headers: list[tuple[bytes, bytes]]) -> str | None:
    for k, v in headers:
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == COOKIE:
                    return val
    return None


class AuthMiddleware:
    """Pure ASGI so it also covers the mounted MCP apps and streaming responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (scope["type"] != "http" or not enabled() or scope["method"] == "OPTIONS" or path in OPEN
                or not path.startswith(PROTECTED)):
            return await self.app(scope, receive, send)
        s = verify(_cookie(scope["headers"]))
        if not s:
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
            return await send({"type": "http.response.body", "body": b'{"detail":"sign in required"}'})
        headers = [(k, v) for k, v in scope["headers"] if k != b"x-user-id"] + [(b"x-user-id", s["u"].encode())]
        qs = [(k, v) for k, v in parse_qsl(scope["query_string"].decode("latin-1"), keep_blank_values=True) if k != "principal"]
        scope = {**scope, "headers": headers, "query_string": urlencode(qs + [("principal", s["u"])]).encode()}
        await self.app(scope, receive, send)


class Login(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict:
    email = body.email.strip().lower()
    fails, until = _FAILS.get(email, (0, 0.0))
    if fails >= MAX_FAILS and time.time() < until:
        raise HTTPException(429, "too many attempts, try again later")
    row = _con().execute("SELECT pw, user_id FROM accounts WHERE email=?", [email]).fetchone()
    if not check_pw(body.password, row[0] if row else _DUMMY) or not row:
        _FAILS[email] = (fails + 1, time.time() + LOCK_S)
        raise HTTPException(401, "wrong email or password")
    _FAILS.pop(email, None)
    response.set_cookie(COOKIE, sign(row[1], email), max_age=TTL, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return {"auth": True, "user_id": row[1], "email": email}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    if not enabled():
        return {"auth": False}
    s = verify(request.cookies.get(COOKIE))
    if not s:
        raise HTTPException(401, "sign in required")
    return {"auth": True, "user_id": s["u"], "email": s["e"]}


def add_account(email: str, password: str, user_id: str) -> None:
    known = {u["user_id"] for u in json.loads((settings.data_dir / "fleet/users.json").read_text())["users"]}
    if user_id not in known:
        raise SystemExit(f"unknown user_id {user_id}; one of: {', '.join(sorted(known))}")
    if len(password) < 10:
        raise SystemExit("password must be at least 10 characters")
    with _con() as con:
        con.execute("INSERT OR REPLACE INTO accounts VALUES (?,?,?)", [email.strip().lower(), hash_pw(password), user_id])


def main() -> None:
    match sys.argv[1:]:
        case ["add", email, user_id]:
            import getpass
            pw = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
            add_account(email, pw, user_id)
            print(f"ok: {email.lower()} signs in as {user_id}")
        case ["list"]:
            for email, user_id in _con().execute("SELECT email, user_id FROM accounts ORDER BY email"):
                print(email, user_id)
        case ["remove", email]:
            with _con() as con:
                print("removed" if con.execute("DELETE FROM accounts WHERE email=?", [email.lower()]).rowcount else "no such account")
        case _:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
