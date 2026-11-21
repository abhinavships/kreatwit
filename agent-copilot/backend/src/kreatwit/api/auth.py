"""Sign-in through Supabase, and the per-request workspace. Off unless AUTH_SECRET is set (local dev, tests, evals).

Supabase owns accounts: sign-up, email verification, password reset. The browser signs in with supabase-js, then
POSTs its access token to /api/auth/session once; the server checks it with Supabase and sets its own signed,
HttpOnly cookie holding only the Supabase user id. On every protected request the middleware looks the account up
in kreatwit.orgs and binds the request to its org's workspace and to the member's own principal: the client's
X-User-Id header and ?principal= are overwritten, so nobody can act as, or read the chats of, someone else.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from urllib.parse import parse_qsl, urlencode

from kreatwit import orgs, workspace
from kreatwit.settings import settings

COOKIE = "kreatwit_session"
TTL = 7 * 24 * 3600
OPEN = {"/api/health", "/api/auth/session", "/api/auth/logout", "/api/auth/config"}
NO_ORG_OK = {"/api/auth/me", "/api/org"}  # signed in but not in an org yet: may see who they are and create one
PROTECTED = ("/api/",)  # everything else is the static site
HIDDEN = ("/mcp", "/skills-mcp")  # MCP for local agent clients; not exposed on a public, multi-account server

router = APIRouter(prefix="/api/auth")


def enabled() -> bool:
    return bool(settings.auth_secret)


def _mac(body: str) -> str:
    return hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def sign(uid: str, email: str, ttl: int = TTL) -> str:
    raw = json.dumps({"u": uid, "e": email, "x": int(time.time()) + ttl}).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")  # no padding: "=" would make the cookie value quoted
    return f"{body}.{_mac(body)}"


def verify(token: str | None) -> dict | None:
    body, _, mac = (token or "").partition(".")
    if not mac or not hmac.compare_digest(_mac(body), mac):
        return None
    try:
        s = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        workspace.check(s.get("u", ""))
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


async def _reply(send, status: int, detail: str) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": json.dumps({"detail": detail}).encode()})


class AuthMiddleware:
    """Pure ASGI so it also covers streaming responses; sets workspace.CURRENT for the whole request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled():
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path.startswith(HIDDEN):
            return await _reply(send, 404, "not found")
        if scope["method"] == "OPTIONS" or path in OPEN or not path.startswith(PROTECTED):
            return await self.app(scope, receive, send)
        s = verify(_cookie(scope["headers"]))
        if not s:
            return await _reply(send, 401, "sign in required")
        scope = {**scope, "state": {**scope.get("state", {}), "session": s}}
        m = orgs.member(s["u"])
        if not m:
            if path in NO_ORG_OK:
                return await self.app(scope, receive, send)
            return await _reply(send, 403, "create or join an organization first")
        # the member is the principal: overwrite whatever persona the client sent
        uid = m["user_id"].encode()
        scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"x-user-id"] + [(b"x-user-id", uid)]
        q = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        if any(k == "principal" for k, _ in q):
            scope["query_string"] = urlencode([(k, m["user_id"] if k == "principal" else v) for k, v in q]).encode()
        t1, t2 = workspace.CURRENT.set(m["org_id"]), orgs.MEMBER.set(m)
        try:
            await self.app(scope, receive, send)
        finally:
            workspace.CURRENT.reset(t1)
            orgs.MEMBER.reset(t2)


def supabase_user(access_token: str) -> dict | None:
    """Ask Supabase who owns this access token (works for any JWT signing setup; one call per sign-in)."""
    r = httpx.get(f"{settings.supabase_url.rstrip('/')}/auth/v1/user", timeout=10,
                  headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {access_token}"})
    return r.json() if r.status_code == 200 else None


class SessionIn(BaseModel):
    access_token: str


@router.get("/config")
def config() -> dict:
    """Public values the browser needs to talk to Supabase (the anon key is meant to be public)."""
    return {"auth": enabled(), "supabase_url": settings.supabase_url, "supabase_anon_key": settings.supabase_anon_key}


@router.post("/session")
def session(body: SessionIn, request: Request, response: Response) -> dict:
    if not enabled():
        raise HTTPException(404, "sign-in is off")
    u = supabase_user(body.access_token)
    if not u or not u.get("id"):
        raise HTTPException(401, "session expired, sign in again")
    if not (u.get("email_confirmed_at") or u.get("confirmed_at")):
        raise HTTPException(403, "confirm your email first")
    try:
        uid = workspace.check(u["id"])
    except ValueError as e:
        raise HTTPException(401, "unexpected account id") from e
    email = u.get("email", "")
    orgs.accept_invite(uid, email)
    response.set_cookie(COOKIE, sign(uid, email), max_age=TTL, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return _me(uid, email)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    if not enabled():
        return {"auth": False}
    s = request.state.session  # the middleware already checked the cookie
    return _me(s["u"], s["e"])


def _me(uid: str, email: str) -> dict:
    m = orgs.member(uid)
    if m:
        m = {k: m[k] for k in ("user_id", "name", "title", "role", "org_id", "org_name", "email")}
    return {"auth": True, "email": email, "member": m, "invite": None if m else orgs.pending_invite(email)}
