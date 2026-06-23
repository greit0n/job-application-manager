from __future__ import annotations

from .conftest import login


def test_requires_auth(client):
    assert client.get("/api/applications").status_code == 401
    assert client.get("/api/profile").status_code == 401


def test_login_me_logout(client):
    login(client)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_bad_credentials(client):
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope"}).status_code == 401


def test_profile_upsert(client):
    login(client)
    # auto-created empty profile
    assert client.get("/api/profile").json()["name"] == ""
    resp = client.put(
        "/api/profile",
        json={"name": "Georgi", "phone": "+43"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Georgi"
    # persisted
    assert client.get("/api/profile").json()["name"] == "Georgi"


def test_application_crud(client):
    login(client)
    created = client.post(
        "/api/applications",
        json={"company": "Greentube", "position": "Lead IT Architect", "language": "de"},
    )
    assert created.status_code == 201
    app_id = created.json()["id"]

    assert client.get("/api/applications").json().__len__() == 1

    patched = client.patch(f"/api/applications/{app_id}", json={"status": "applied", "notes": "sent"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "applied"

    # invalid status rejected
    assert client.patch(f"/api/applications/{app_id}", json={"status": "bogus"}).status_code == 422

    assert client.delete(f"/api/applications/{app_id}").status_code == 204
    assert client.get(f"/api/applications/{app_id}").status_code == 404


def test_cv_upload_download_roundtrip(client):
    login(client)
    pdf = b"%PDF-1.4 fake cv bytes"
    resp = client.post(
        "/api/cvs",
        files={"file": ("CV_Fullstack.pdf", pdf, "application/pdf")},
        data={"label": "Fullstack", "language": "de", "is_default": "true"},
    )
    assert resp.status_code == 201, resp.text
    cv = resp.json()
    assert cv["label"] == "Fullstack" and cv["is_default"] is True and cv["size"] == len(pdf)

    dl = client.get(f"/api/cvs/{cv['id']}/download")
    assert dl.status_code == 200
    assert dl.content == pdf


def test_user_scoping(client):
    login(client, "a@example.com", "pw-a")
    app_id = client.post("/api/applications", json={"company": "A-Corp"}).json()["id"]

    # switch to user B on the same client (session cookie replaced)
    login(client, "b@example.com", "pw-b")
    assert client.get(f"/api/applications/{app_id}").status_code == 404
    assert client.get("/api/applications").json() == []


def test_profile_drops_content_fields(client):
    login(client)
    resp = client.put(
        "/api/profile",
        json={
            "name": "Georgi", "address": "Wien", "phone": "+43", "email": "g@example.com",
            "languages": "German native", "availability": "Immediate",
            "preferences": "Remote ok",
            # legacy keys a stale client might still send — must be ignored, not stored:
            "headline": "X", "skills": "Y", "summary": "Z", "employers": [{"name": "Old"}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Georgi"
    for gone in ("headline", "skills", "summary", "employers"):
        assert gone not in body
