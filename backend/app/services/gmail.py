"""Direct Gmail OAuth and draft API client.

Uses REST endpoints directly. The app only creates or replaces drafts; sending
is intentionally out of scope.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP

import httpx

from ..config import Settings, get_settings


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailAPIError(Exception):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    refresh_token: str = ""
    token_type: str = "Bearer"
    scope: str = ""
    expires_in: int | None = None


class GmailClient:
    def __init__(self, settings: Settings | None = None, *, timeout: float = 20.0):
        self.settings = settings or get_settings()
        self.timeout = timeout

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthToken:
        data = {
            "code": code,
            "client_id": self.settings.gmail_oauth_client_id,
            "client_secret": self.settings.gmail_oauth_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        payload = self._post_form(GOOGLE_TOKEN_URL, data)
        return _oauth_token(payload)

    def refresh_access_token(self, refresh_token: str) -> OAuthToken:
        data = {
            "client_id": self.settings.gmail_oauth_client_id,
            "client_secret": self.settings.gmail_oauth_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        payload = self._post_form(GOOGLE_TOKEN_URL, data)
        return _oauth_token(payload)

    def revoke_token(self, token: str) -> None:
        if not token:
            return
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                GOOGLE_REVOKE_URL,
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        if response.status_code not in (200, 400):
            raise GmailAPIError(f"Google token revocation failed ({response.status_code})")

    def get_profile(self, access_token: str) -> dict:
        return self._get_json(f"{GMAIL_API_BASE}/profile", access_token)

    def create_draft(self, access_token: str, raw: str) -> dict:
        return self._send_draft("POST", f"{GMAIL_API_BASE}/drafts", access_token, raw)

    def update_draft(self, access_token: str, draft_id: str, raw: str) -> dict:
        return self._send_draft("PUT", f"{GMAIL_API_BASE}/drafts/{draft_id}", access_token, raw)

    def _send_draft(self, method: str, url: str, access_token: str, raw: str) -> dict:
        body = {"message": {"raw": raw}}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
        return _response_json(response)

    def _get_json(self, url: str, access_token: str) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        return _response_json(response)

    def _post_form(self, url: str, data: dict[str, str]) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, data=data)
        return _response_json(response)


def get_gmail_client() -> GmailClient:
    return GmailClient()


def build_raw_message(
    *,
    from_email: str,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> str:
    message = EmailMessage(policy=SMTP)
    if from_email:
        message["From"] = _clean_header(from_email)
    if to:
        message["To"] = _clean_header(to)
    if cc:
        message["Cc"] = _clean_header(cc)
    if bcc:
        message["Bcc"] = _clean_header(bcc)
    message["Subject"] = _clean_header(subject)
    message.set_content(body or "", charset="utf-8")
    for filename, data, mime in attachments or []:
        if not data:
            continue
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype.split(";", 1)[0],
            filename=_clean_header(filename),
        )
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _clean_header(value: str) -> str:
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split())


def _oauth_token(payload: dict) -> OAuthToken:
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise GmailAPIError("Google did not return an access token")
    expires_in = payload.get("expires_in")
    return OAuthToken(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or ""),
        token_type=str(payload.get("token_type") or "Bearer"),
        scope=str(payload.get("scope") or ""),
        expires_in=int(expires_in) if expires_in is not None else None,
    )


def _response_json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        detail = payload.get("error_description") or payload.get("error") or response.text
        raise GmailAPIError(f"Gmail API request failed: {detail}", status_code=response.status_code)
    return payload
