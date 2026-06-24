from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import get_db
from app.models import GmailConnection, User
from app.routers.gmail import get_gmail_client
from app.services.gmail import OAuthToken

from .conftest import login


class FakeGmailClient:
    def __init__(self):
        self.exchanged_codes: list[str] = []
        self.refreshed_tokens: list[str] = []
        self.revoked_tokens: list[str] = []
        self.created: list[dict] = []
        self.updated: list[dict] = []

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthToken:
        self.exchanged_codes.append(code)
        return OAuthToken(
            access_token="access-1",
            refresh_token="refresh-1",
            token_type="Bearer",
            scope="https://www.googleapis.com/auth/gmail.compose",
            expires_in=3600,
        )

    def refresh_access_token(self, refresh_token: str) -> OAuthToken:
        self.refreshed_tokens.append(refresh_token)
        return OAuthToken(
            access_token="access-refreshed",
            token_type="Bearer",
            scope="https://www.googleapis.com/auth/gmail.compose",
            expires_in=3600,
        )

    def revoke_token(self, token: str) -> None:
        self.revoked_tokens.append(token)

    def get_profile(self, access_token: str) -> dict:
        return {"emailAddress": "gmail@example.com"}

    def create_draft(self, access_token: str, raw: str) -> dict:
        self.created.append({"access_token": access_token, "raw": raw})
        return {"id": "draft-1", "message": {"id": "msg-1"}}

    def update_draft(self, access_token: str, draft_id: str, raw: str) -> dict:
        self.updated.append({"access_token": access_token, "draft_id": draft_id, "raw": raw})
        return {"id": draft_id, "message": {"id": "msg-2"}}


@pytest.fixture
def gmail_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gmail_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "gmail_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "gmail_oauth_redirect_uri", "https://jobs.test/api/gmail/callback")
    monkeypatch.setattr(settings, "gmail_oauth_success_url", "/?gmail=connected")
    monkeypatch.setattr(settings, "gmail_token_encryption_key", "test-gmail-token-secret")
    return settings


@pytest.fixture
def fake_gmail(app_ctx):
    fake = FakeGmailClient()
    app_ctx.dependency_overrides[get_gmail_client] = lambda: fake
    yield fake
    app_ctx.dependency_overrides.pop(get_gmail_client, None)


@contextmanager
def db_session(app_ctx):
    override = app_ctx.dependency_overrides[get_db]
    gen = override()
    db = next(gen)
    try:
        yield db
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def _connect_gmail(client, code: str = "oauth-code") -> None:
    connect = client.get("/api/gmail/connect", follow_redirects=False)
    assert connect.status_code in (302, 307), connect.text
    query = parse_qs(urlparse(connect.headers["location"]).query)
    assert query["client_id"] == ["client-id"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.compose"]

    state = query["state"][0]
    callback = client.get(f"/api/gmail/callback?code={code}&state={state}", follow_redirects=False)
    assert callback.status_code == 303, callback.text
    assert callback.headers["location"] == "/?gmail=connected"


def _create_application_with_email(client) -> int:
    profile = client.put(
        "/api/profile",
        json={"name": "Georg", "address": "Wien", "phone": "+43", "email": "georg@example.com"},
    )
    assert profile.status_code == 200, profile.text
    created = client.post(
        "/api/applications",
        json={
            "company": "Acme",
            "position": "Engineer",
            "recipient_email": "jobs@example.com",
        },
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    patched = client.patch(
        f"/api/applications/{app_id}",
        json={
            "email_subject": "Application for Engineer",
            "email_body": "Hello Acme,\n\nPlease find my application attached.",
        },
    )
    assert patched.status_code == 200, patched.text
    return app_id


def _decode_raw(raw: str) -> str:
    return base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")


def test_gmail_oauth_callback_stores_encrypted_connection(client, app_ctx, fake_gmail, gmail_settings):
    login(client)
    status = client.get("/api/gmail/status")
    assert status.status_code == 200
    assert status.json() == {
        "configured": True,
        "connected": False,
        "email": "",
        "scope": "",
        "expires_at": None,
    }

    _connect_gmail(client)

    assert fake_gmail.exchanged_codes == ["oauth-code"]
    status = client.get("/api/gmail/status").json()
    assert status["connected"] is True
    assert status["email"] == "gmail@example.com"

    with db_session(app_ctx) as db:
        user = db.scalar(select(User).where(User.email == "a@example.com"))
        connection = db.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))
        assert connection is not None
        assert connection.access_token_encrypted != "access-1"
        assert connection.refresh_token_encrypted != "refresh-1"


def test_gmail_draft_create_then_update_uses_mime_base64url(client, fake_gmail, gmail_settings):
    login(client)
    _connect_gmail(client)
    app_id = _create_application_with_email(client)

    created = client.post(f"/api/applications/{app_id}/gmail-draft", json={"to": "jobs@example.com"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["gmail_draft_id"] == "draft-1"
    assert body["to_email"] == "jobs@example.com"
    assert body["application"]["gmail_draft_id"] == "draft-1"

    decoded = _decode_raw(fake_gmail.created[0]["raw"])
    assert "From: gmail@example.com" in decoded
    assert "To: jobs@example.com" in decoded
    assert "Subject: Application for Engineer" in decoded
    assert "Please find my application attached." in decoded

    updated = client.post(
        f"/api/applications/{app_id}/gmail-draft",
        json={"to": "jobs@example.com", "subject": "Updated subject", "body": "Updated body"},
    )
    assert updated.status_code == 200, updated.text
    assert fake_gmail.updated[0]["draft_id"] == "draft-1"
    assert updated.json()["gmail_draft_id"] == "draft-1"
    assert "Subject: Updated subject" in _decode_raw(fake_gmail.updated[0]["raw"])


def test_gmail_draft_refreshes_expired_access_token(client, app_ctx, fake_gmail, gmail_settings):
    login(client)
    _connect_gmail(client)
    app_id = _create_application_with_email(client)

    with db_session(app_ctx) as db:
        user = db.scalar(select(User).where(User.email == "a@example.com"))
        connection = db.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))
        connection.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()

    resp = client.post(f"/api/applications/{app_id}/gmail-draft", json={"to": "jobs@example.com"})
    assert resp.status_code == 200, resp.text
    assert fake_gmail.refreshed_tokens == ["refresh-1"]
    assert fake_gmail.created[0]["access_token"] == "access-refreshed"


def test_gmail_disconnect_removes_connection(client, app_ctx, fake_gmail, gmail_settings):
    login(client)
    _connect_gmail(client)
    app_id = _create_application_with_email(client)
    assert client.post(f"/api/applications/{app_id}/gmail-draft", json={"to": "jobs@example.com"}).status_code == 200

    resp = client.delete("/api/gmail/disconnect")
    assert resp.status_code == 204
    assert fake_gmail.revoked_tokens == ["refresh-1"]
    assert client.get("/api/gmail/status").json()["connected"] is False

    with db_session(app_ctx) as db:
        assert db.scalar(select(GmailConnection)) is None


def test_gmail_draft_is_scoped_to_current_user(client, fake_gmail, gmail_settings):
    login(client, "a@example.com", "pw-a")
    _connect_gmail(client)
    app_id = _create_application_with_email(client)

    login(client, "b@example.com", "pw-b")
    resp = client.post(f"/api/applications/{app_id}/gmail-draft", json={"to": "jobs@example.com"})
    assert resp.status_code == 404
    assert fake_gmail.created == []
