"""/api/org: create an organization, manage members, invites and roles. Rules live in kreatwit.orgs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from kreatwit import orgs

router = APIRouter(prefix="/api/org")


class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    your_name: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=80)
    sample: bool = False  # start from the sample oil-field dataset instead of an empty workspace


class JoinIn(BaseModel):
    org_id: str = Field(min_length=36, max_length=36)
    your_name: str = Field(min_length=1, max_length=80)


class InviteIn(BaseModel):
    email: str = Field(max_length=254)
    role: str = "member"


class RoleIn(BaseModel):
    role: str


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=80)


class RenameIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


def _me() -> dict:
    m = orgs.MEMBER.get()
    if not m:
        raise HTTPException(404, "sign-in is off or you are not in an organization")
    return m


@router.get("")
def org() -> dict:
    me = _me()
    admin = orgs.rank(me["role"]) >= orgs.rank("admin")
    return {"org": {"org_id": me["org_id"], "name": me["org_name"]}, "me": {k: me[k] for k in ("user_id", "role")},
            "members": orgs.members(me["org_id"]), "invites": orgs.invites(me["org_id"]) if admin else [],
            "requests": orgs.requests(me["org_id"]) if admin else []}


def _session(request: Request) -> dict:
    s = getattr(request.state, "session", None)
    if not s:
        raise HTTPException(404, "sign-in is off")
    return s


@router.post("/join")
def join(body: JoinIn, request: Request) -> dict:
    s = _session(request)
    return orgs.request_join(s["u"], s["e"], body.your_name, body.org_id)


@router.delete("/join")
def cancel_join(request: Request) -> dict:
    orgs.cancel_request(_session(request)["u"])
    return {"ok": True}


@router.post("/requests/{email}")
def approve(email: str, body: RoleIn) -> dict:
    orgs.approve(orgs.require("admin") or _me(), email, body.role)
    return {"ok": True}


@router.delete("/requests/{email}")
def decline(email: str) -> dict:
    orgs.decline(orgs.require("admin") or _me(), email)
    return {"ok": True}


@router.post("")
def create(body: OrgIn, request: Request) -> dict:
    s = _session(request)
    m = orgs.create(s["u"], s["e"], body.your_name, body.name, body.title, body.sample)
    return {"org_id": m["org_id"], "name": m["org_name"]}


@router.patch("")
def rename(body: RenameIn) -> dict:
    orgs.rename(orgs.require("admin") or _me(), body.name)
    return {"ok": True}


@router.post("/invites")
def invite(body: InviteIn) -> dict:
    orgs.invite(orgs.require("admin") or _me(), body.email, body.role)
    return {"ok": True}


@router.delete("/invites/{email}")
def revoke(email: str) -> dict:
    orgs.revoke(orgs.require("admin") or _me(), email)
    return {"ok": True}


@router.patch("/members/{user_id}")
def set_role(user_id: str, body: RoleIn) -> dict:
    orgs.set_role(orgs.require("admin") or _me(), user_id, body.role)
    return {"ok": True}


@router.delete("/members/{user_id}")
def remove(user_id: str) -> dict:
    me = _me()
    if user_id != me["user_id"]:
        orgs.require("admin")
    orgs.remove(me, user_id)
    return {"ok": True}


@router.patch("/me")
def profile(body: ProfileIn) -> dict:
    m = orgs.update_profile(_me(), body.name, body.title)
    return {"name": m["name"], "title": m["title"]}
