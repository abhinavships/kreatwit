"""Public-server mode: Supabase sign-in, one sandboxed database per account, daily caps.

The probes here are the ones that matter for a multi-account deploy: nothing one account stores is visible to
another, through the API, the agent's SQL, or the agent's file tools.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from kreatwit import tools, usage, workspace
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
         "tok-new": {"id": "cccccccc-0000-4000-8000-000000000003", "email": "c@example.com"}}


@pytest.fixture
def server(db, tmp_path, monkeypatch):
    db.run("CHECKPOINT")
    shutil.copyfile(db.path, tmp_path / "template.duckdb")  # the template every workspace starts from
    monkeypatch.setattr(settings, "db_path", tmp_path / "template.duckdb")
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(auth, "supabase_user", lambda token: USERS.get(token))
    monkeypatch.setattr(workspace, "uploads_dir", lambda ws=None: tmp_path / "uploads" / (ws or workspace.CURRENT.get() or ""))
    monkeypatch.setattr(usage, "_CON", None)
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
    assert a.get("/api/auth/me").json() == {"auth": True, "email": "a@example.com"}
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


def test_accounts_cannot_see_each_other(server):
    a, b = signed_in("tok-a"), signed_in("tok-b")
    up = a.post("/api/ingest", content=b"# Field memo\n\nThe ZEBRA-42 valve is leaking.\n",
                headers={"X-Filename": "memo.md", "Content-Type": "text/markdown"})
    assert up.status_code == 200, up.text
    assert a.post("/api/canvases", json={"name": "a-only", "cards": []}).status_code == 200

    assert [c["name"] for c in b.get("/api/canvases").json()["canvases"]] == []
    assert workspace.get(A).rows("SELECT count(*) n FROM docs WHERE text LIKE '%ZEBRA-42%'")[0]["n"] >= 1
    assert workspace.get(B).rows("SELECT count(*) n FROM docs WHERE text LIKE '%ZEBRA-42%'")[0]["n"] == 0

    # B's agent cannot reach A's files: not through SQL file functions, ATTACH, or the ingest tool
    a_dir = workspace.uploads_dir(A).resolve()
    (a_dir / "x.json").write_text('{"secret": "ZEBRA-42"}\n')
    token = workspace.CURRENT.set(A)
    try:  # control: the owner can read its own folder, so B's failure below is the sandbox, not a bad query
        own = sql(RunDeps(principal="U-101", chat_id="c-a", today=settings.clock_today),
                  f"SELECT * FROM read_ndjson_auto('{a_dir}/x.json')")
        assert own.preview == [{"secret": "ZEBRA-42"}]
    finally:
        workspace.CURRENT.reset(token)
    token = workspace.CURRENT.set(B)
    try:
        deps = RunDeps(principal="U-101", chat_id="c-b", today=settings.clock_today)
        for q in (f"SELECT * FROM read_text('{a_dir}/*')", f"SELECT * FROM read_ndjson_auto('{a_dir}/x.json')",
                  "SELECT * FROM sqlite_scan('/etc/hosts', 'x')"):
            with pytest.raises(ToolError):
                sql(deps, q)
        for path in ("/etc/hosts", f"{a_dir}/memo.md", "../" + A + "/memo.md"):
            with pytest.raises(ToolError):
                ingest_file_tool(deps, path)
    finally:
        workspace.CURRENT.reset(token)


def test_chat_ids_are_owned(server):
    a, b = signed_in("tok-a"), signed_in("tok-b")
    assert a.post("/api/assertions/none/undo", headers={"X-Chat-Id": "chat-shared"}).status_code == 404  # A claims it
    assert b.post("/api/assertions/none/undo", headers={"X-Chat-Id": "chat-shared"}).status_code == 403


def test_daily_upload_cap(server, monkeypatch):
    monkeypatch.setattr(settings, "daily_uploads", 1)
    a = signed_in("tok-a")
    send = lambda: a.post("/api/ingest", content=b"# n\n\ntext\n", headers={"X-Filename": "n.md"})  # noqa: E731
    assert send().status_code == 200
    assert send().status_code == 429
