"""Public-server mode: Supabase sign-in, organizations with roles, one sandboxed database per org, daily caps.

The probes here are the ones that matter for a multi-tenant deploy: nothing one org stores is visible to another
(through the API, the agent's SQL, or the agent's file tools); inside an org, nobody can act as someone else,
and roles are enforced on the server.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from kreatwit import orgs, tools, usage, workspace
from kreatwit.api import app as app_module
from kreatwit.api import auth
from kreatwit.api.app import app
from kreatwit.contracts import RunDeps
from kreatwit.settings import settings
from kreatwit.tools.core import ToolError
from kreatwit.tools.docs import sql
from kreatwit.tools.ingest_tools import ingest_file_tool

A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"
USERS = {"tok-a": {"id": A, "email": "a@example.com", "email_confirmed_at": "2026-11-21"},
         "tok-b": {"id": B, "email": "b@example.com", "email_confirmed_at": "2026-11-21"},
         "tok-new": {"id": "cccccccc-0000-4000-8000-000000000003", "email": "c@example.com"},
         "tok-a2": {"id": "dddddddd-0000-4000-8000-000000000004", "email": "a2@example.com", "email_confirmed_at": "x"},
         "tok-v": {"id": "eeeeeeee-0000-4000-8000-000000000005", "email": "v@example.com", "email_confirmed_at": "x"}}


@pytest.fixture
def server(db, tmp_path, monkeypatch):
    db.run("CHECKPOINT")
    shutil.copyfile(db.path, tmp_path / "template.duckdb")  # the template every workspace starts from
    monkeypatch.setattr(settings, "db_path", tmp_path / "template.duckdb")
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(auth, "supabase_user", lambda token: USERS.get(token))
    monkeypatch.setattr(workspace, "uploads_dir", lambda ws=None: tmp_path / "uploads" / (ws or workspace.CURRENT.get() or ""))
    monkeypatch.setattr(usage, "_CON", None)
    monkeypatch.setattr(orgs, "_CON", None)
    tools.set_db(None)  # leave the shared test db; each account gets its own
    yield
    for d in workspace._OPEN.values():
        d.close()
    workspace._OPEN.clear()
    app_module._CHAT_OWNER.clear()
    tools.set_db(db)


def signed_in(token: str) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/auth/session", json={"access_token": token}).status_code == 200
    return c


def founder(token: str, org: str) -> tuple[TestClient, str]:
    """Signs in and creates an org; returns the client and the org id."""
    c = signed_in(token)
    r = c.post("/api/org", json={"name": org, "your_name": org + " founder"})
    assert r.status_code == 200, r.text
    return c, r.json()["org_id"]


def joined(owner: TestClient, token: str, role: str) -> TestClient:
    assert owner.post("/api/org/invites", json={"email": USERS[token]["email"], "role": role}).status_code == 200
    return signed_in(token)


def test_sign_in_required(server):
    c = TestClient(app)
    assert c.get("/api/users").status_code == 401
    assert c.get("/api/chats?principal=U-101").status_code == 401
    assert c.post("/mcp/", json={}).status_code == 404  # local-agent MCP is not public
    assert c.get("/api/health").json()["ok"] is True
    assert c.get("/api/auth/config").json()["auth"] is True


def test_session_exchange(server):
    c = TestClient(app)
    assert c.post("/api/auth/session", json={"access_token": "forged"}).status_code == 401
    assert c.post("/api/auth/session", json={"access_token": "tok-new"}).status_code == 403  # email not confirmed
    a = signed_in("tok-a")
    assert a.get("/api/auth/me").json() == {"auth": True, "email": "a@example.com", "member": None, "invite": None}
    assert a.get("/api/users").status_code == 403  # signed in, but no org yet
    a.post("/api/org", json={"name": "Acme", "your_name": "Asha", "title": "Ops lead"})
    me = a.get("/api/auth/me").json()["member"]
    assert (me["org_name"], me["name"], me["role"]) == ("Acme", "Asha", "owner") and me["user_id"].startswith("M-")
    assert a.post("/api/org", json={"name": "Second", "your_name": "Asha"}).status_code == 409
    assert a.get("/api/users").status_code == 200
    a.post("/api/auth/logout")
    assert a.get("/api/users").status_code == 401


def test_tampered_or_expired_cookie_rejected(server):
    good = auth.sign(A, "a@example.com")
    body, mac = good.split(".")
    forged = auth.sign(B, "a@example.com").split(".")[0] + "." + mac
    for token in (forged, body + ".00", auth.sign(A, "a@example.com", ttl=-1), auth.sign("../../etc", "x")):
        c = TestClient(app)
        c.cookies.set(auth.COOKIE, token)
        assert c.get("/api/users").status_code == 401


def test_orgs_cannot_see_each_other(server):
    (a, org_a), (b, org_b) = founder("tok-a", "Acme"), founder("tok-b", "Bolt")
    up = a.post("/api/ingest", content=b"# Field memo\n\nThe ZEBRA-42 valve is leaking.\n",
                headers={"X-Filename": "memo.md", "Content-Type": "text/markdown"})
    assert up.status_code == 200, up.text
    assert a.post("/api/canvases", json={"name": "a-only", "cards": []}).status_code == 200

    assert [c["name"] for c in b.get("/api/canvases").json()["canvases"]] == []
    assert b.get("/api/ingest/history").json()["items"] == []
    assert workspace.get(org_a).rows("SELECT count(*) n FROM docs WHERE text LIKE '%ZEBRA-42%'")[0]["n"] >= 1
    assert workspace.get(org_b).rows("SELECT count(*) n FROM docs WHERE text LIKE '%ZEBRA-42%'")[0]["n"] == 0
    assert [m["email"] for m in b.get("/api/org").json()["members"]] == ["b@example.com"]

    # B's agent cannot reach A's files: not through SQL file functions, ATTACH, or the ingest tool
    a_dir = workspace.uploads_dir(org_a).resolve()
    (a_dir / "x.json").write_text('{"secret": "ZEBRA-42"}\n')
    token = workspace.CURRENT.set(org_a)
    try:  # control: the org can read its own folder, so B's failure below is the sandbox, not a bad query
        own = sql(RunDeps(principal="U-101", chat_id="c-a", today=settings.clock_today),
                  f"SELECT * FROM read_ndjson_auto('{a_dir}/x.json')")
        assert own.preview == [{"secret": "ZEBRA-42"}]
    finally:
        workspace.CURRENT.reset(token)
    token = workspace.CURRENT.set(org_b)
    try:
        deps = RunDeps(principal="U-101", chat_id="c-b", today=settings.clock_today)
        for q in (f"SELECT * FROM read_text('{a_dir}/*')", f"SELECT * FROM read_ndjson_auto('{a_dir}/x.json')",
                  "SELECT * FROM sqlite_scan('/etc/hosts', 'x')", f"ATTACH '{workspace.db_file(org_a)}' AS a"):
            with pytest.raises(ToolError):
                sql(deps, q)
        for path in ("/etc/hosts", f"{a_dir}/memo.md", "../" + org_a + "/memo.md"):
            with pytest.raises(ToolError):
                ingest_file_tool(deps, path)
    finally:
        workspace.CURRENT.reset(token)


def test_members_share_org_data_but_not_identity(server):
    a, org_a = founder("tok-a", "Acme")
    a2 = joined(a, "tok-a2", "member")
    me_a = a.get("/api/auth/me").json()["member"]["user_id"]
    me_a2 = a2.get("/api/auth/me").json()["member"]
    assert me_a2["org_id"] == org_a and me_a2["role"] == "member"
    assert a2.post("/api/ingest", content=b"# Shift note\n\nPump 7 restarted.\n", headers={"X-Filename": "s.md"}).status_code == 200
    seen = a.get("/api/ingest/history").json()["items"]  # org-level data: A sees what A2 uploaded, attributed to A2
    assert [(u["file"].rsplit("/", 1)[-1], u["principal"]) for u in seen] == [("s.md", me_a2["user_id"])]
    # members appear in the org's people table, so answers can name them
    assert workspace.get(org_a).rows("SELECT name FROM users WHERE user_id=?", [me_a])[0]["name"] == "Acme founder"

    # a member cannot act as anyone else: the persona header and ?principal= are overwritten server-side
    assert a.post("/api/canvases", json={"name": "a-board", "cards": []}).status_code == 200
    spoof = a2.get("/api/canvases", headers={"X-User-Id": me_a})
    assert [c["name"] for c in spoof.json()["canvases"]] == []
    workspace.get(org_a).run("INSERT INTO episodes (episode_id, chat_id, principal, utterance, ts, forgotten) VALUES ('e1', 'c1', ?, 'hi', now(), false)", [me_a])
    assert len(a.get(f"/api/chats?principal={me_a}").json()["chats"]) == 1
    assert a2.get(f"/api/chats?principal={me_a}").json()["chats"] == []
    # a chat belongs to one member
    assert a.post("/api/assertions/none/undo", headers={"X-Chat-Id": "chat-x"}).status_code == 404  # A claims it
    assert a2.post("/api/assertions/none/undo", headers={"X-Chat-Id": "chat-x"}).status_code == 403


def test_roles_are_enforced(server):
    a, _ = founder("tok-a", "Acme")
    v = joined(a, "tok-v", "viewer")
    assert v.post("/api/ingest", content=b"# x\n\ny\n", headers={"X-Filename": "x.md"}).status_code == 403
    assert v.post("/api/disputes/d1/resolve", json={"action": "keep"}).status_code == 403
    assert v.post("/api/org/invites", json={"email": "z@example.com", "role": "viewer"}).status_code == 403
    assert v.get("/api/org").json()["invites"] == []  # only admins see pending invites
    assert v.get("/api/users").status_code == 200  # but can read and ask

    vid = v.get("/api/auth/me").json()["member"]["user_id"]
    aid = a.get("/api/auth/me").json()["member"]["user_id"]
    assert a.patch(f"/api/org/members/{vid}", json={"role": "admin"}).status_code == 200
    assert v.post("/api/org/invites", json={"email": "z@example.com", "role": "member"}).status_code == 200
    assert v.post("/api/org/invites", json={"email": "y@example.com", "role": "owner"}).status_code == 403
    assert v.patch(f"/api/org/members/{aid}", json={"role": "viewer"}).status_code == 403  # admin cannot touch owner
    assert a.patch(f"/api/org/members/{aid}", json={"role": "admin"}).status_code == 409  # last owner stays
    assert a.post("/api/org/invites", json={"email": "a2@example.com", "role": "bogus"}).status_code == 400

    assert a.delete(f"/api/org/members/{vid}").status_code == 200
    assert v.get("/api/users").status_code == 403  # removal takes effect at once, cookie or not


def test_daily_upload_cap_is_per_member(server, monkeypatch):
    monkeypatch.setattr(settings, "daily_uploads", 1)
    a, _ = founder("tok-a", "Acme")
    a2 = joined(a, "tok-a2", "member")
    send = lambda c: c.post("/api/ingest", content=b"# n\n\ntext\n", headers={"X-Filename": "n.md"})  # noqa: E731
    assert send(a).status_code == 200
    assert send(a).status_code == 429
    assert send(a2).status_code == 200
