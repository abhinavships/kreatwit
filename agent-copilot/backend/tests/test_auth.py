"""Auth on: no cookie -> 401; a signed-in user cannot act as anyone else, whatever the client sends."""

import pytest
from fastapi.testclient import TestClient

from kreatwit.api import auth
from kreatwit.api.app import app
from kreatwit.settings import settings


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "db_path", tmp_path / "x.duckdb")  # accounts.sqlite lands next to it
    auth._FAILS.clear()
    auth.add_account("Emily@Example.com", "correct horse battery", "U-101")
    return TestClient(app)


def test_requires_sign_in(client):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/chats?principal=U-101").status_code == 401
    assert client.post("/mcp/", json={}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_login_and_identity_cannot_be_spoofed(client, db):
    assert client.post("/api/auth/login", json={"email": "emily@example.com", "password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "emily@example.com", "password": "correct horse battery"})
    assert r.status_code == 200 and r.json()["user_id"] == "U-101"
    assert client.get("/api/auth/me").json()["user_id"] == "U-101"
    # the client claims to be U-201 in both the header and the query: the server uses the session's user
    made = client.post("/api/canvases", headers={"X-User-Id": "U-201"}, json={"name": "mine", "cards": []})
    assert made.status_code == 200
    assert db.rows("SELECT principal FROM canvases WHERE name='mine'") == [{"principal": "U-101"}]
    db.run("DELETE FROM canvases WHERE name='mine'")
    assert client.get("/api/chats?principal=U-201").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/users").status_code == 401


def test_tampered_or_expired_session_rejected(client):
    good = auth.sign("U-101", "emily@example.com")
    assert good.replace(".", "").replace("-", "").replace("_", "").isalnum()  # cookie-safe: never quoted in transit
    body, mac = good.split(".")
    forged = auth.sign("U-201", "emily@example.com").split(".")[0] + "." + mac
    for token in (forged, body + ".00", auth.sign("U-101", "emily@example.com", ttl=-1)):
        client.cookies.set(auth.COOKIE, token)
        assert client.get("/api/users").status_code == 401


def test_lockout_after_repeated_failures(client):
    for _ in range(auth.MAX_FAILS):
        client.post("/api/auth/login", json={"email": "emily@example.com", "password": "nope"})
    r = client.post("/api/auth/login", json={"email": "emily@example.com", "password": "correct horse battery"})
    assert r.status_code == 429
