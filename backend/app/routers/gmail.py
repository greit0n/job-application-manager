"""Gmail OAuth connection and draft creation endpoints."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import Settings, get_settings
from ..db import get_db
from ..models import Application, CVVariant, GmailConnection, User
from ..schemas import GmailDraftOut, GmailDraftRequest, GmailStatusOut
from ..services.gmail import GOOGLE_AUTH_URL, GmailAPIError, GmailClient, build_raw_message, get_gmail_client
from ..services import packet as packet_svc
from ..services.storage import get_storage
from ..services.token_crypto import get_token_cipher

router = APIRouter(tags=["gmail"])

_OAUTH_STATE_KEY = "gmail_oauth_state"
_TOKEN_REFRESH_SKEW = timedelta(seconds=60)


def _gmail_configured(settings: Settings) -> bool:
    return bool(settings.gmail_oauth_client_id and settings.gmail_oauth_client_secret)


def _redirect_uri(request: Request, settings: Settings) -> str:
    return settings.gmail_oauth_redirect_uri or str(request.url_for("gmail_callback"))


def _owned_app(db: Session, user: User, app_id: int) -> Application:
    app = db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return app


def _connection(db: Session, user: User) -> GmailConnection | None:
    return db.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))


def _expires_at(expires_in: int | None) -> datetime | None:
    if expires_in is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(value: datetime | None) -> bool:
    expires_at = _as_utc(value)
    return expires_at is not None and expires_at <= datetime.now(timezone.utc) + _TOKEN_REFRESH_SKEW


def _store_connection_token(
    *,
    db: Session,
    user: User,
    connection: GmailConnection | None,
    gmail_email: str,
    access_token: str,
    refresh_token: str,
    token_type: str,
    scope: str,
    expires_at: datetime | None,
    settings: Settings,
) -> GmailConnection:
    cipher = get_token_cipher(settings)
    if connection is None:
        connection = GmailConnection(user_id=user.id)
        db.add(connection)

    connection.gmail_email = gmail_email
    connection.access_token_encrypted = cipher.encrypt(access_token)
    if refresh_token:
        connection.refresh_token_encrypted = cipher.encrypt(refresh_token)
    connection.token_type = token_type or "Bearer"
    if scope:
        connection.scope = scope
    connection.expires_at = expires_at
    db.commit()
    db.refresh(connection)
    return connection


def _access_token(
    *,
    db: Session,
    connection: GmailConnection,
    gmail: GmailClient,
    settings: Settings,
) -> str:
    cipher = get_token_cipher(settings)
    if not _is_expired(connection.expires_at):
        return cipher.decrypt(connection.access_token_encrypted)

    refresh_token = cipher.decrypt(connection.refresh_token_encrypted)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail connection needs to be reconnected.",
        )

    try:
        token = gmail.refresh_access_token(refresh_token)
    except GmailAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail connection needs to be reconnected.",
        ) from exc

    connection.access_token_encrypted = cipher.encrypt(token.access_token)
    if token.refresh_token:
        connection.refresh_token_encrypted = cipher.encrypt(token.refresh_token)
    connection.token_type = token.token_type or connection.token_type
    if token.scope:
        connection.scope = token.scope
    connection.expires_at = _expires_at(token.expires_in)
    db.commit()
    db.refresh(connection)
    return token.access_token


@router.get("/gmail/status", response_model=GmailStatusOut)
def gmail_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GmailStatusOut:
    connection = _connection(db, user)
    return GmailStatusOut(
        configured=_gmail_configured(settings),
        connected=connection is not None,
        email=connection.gmail_email if connection is not None else "",
        scope=connection.scope if connection is not None else "",
        expires_at=connection.expires_at if connection is not None else None,
    )


@router.get("/gmail/connect")
def gmail_connect(
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if not _gmail_configured(settings):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gmail OAuth is not configured")

    state = secrets.token_urlsafe(32)
    request.session[_OAUTH_STATE_KEY] = {"state": state, "user_id": user.id}
    params = {
        "client_id": settings.gmail_oauth_client_id,
        "redirect_uri": _redirect_uri(request, settings),
        "response_type": "code",
        "scope": settings.gmail_oauth_scopes,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/gmail/callback", name="gmail_callback")
def gmail_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    gmail: GmailClient = Depends(get_gmail_client),
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth failed: {error}")
    pending = request.session.get(_OAUTH_STATE_KEY) or {}
    if pending.get("state") != state or pending.get("user_id") != user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Gmail OAuth state")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Google OAuth code")
    if not _gmail_configured(settings):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gmail OAuth is not configured")

    existing = _connection(db, user)
    cipher = get_token_cipher(settings)
    try:
        token = gmail.exchange_code(code, _redirect_uri(request, settings))
        profile = gmail.get_profile(token.access_token)
    except GmailAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    refresh_token = token.refresh_token
    if not refresh_token and existing is not None:
        refresh_token = cipher.decrypt(existing.refresh_token_encrypted)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Google did not return a refresh token")

    _store_connection_token(
        db=db,
        user=user,
        connection=existing,
        gmail_email=str(profile.get("emailAddress") or ""),
        access_token=token.access_token,
        refresh_token=refresh_token,
        token_type=token.token_type,
        scope=token.scope,
        expires_at=_expires_at(token.expires_in),
        settings=settings,
    )
    request.session.pop(_OAUTH_STATE_KEY, None)
    return RedirectResponse(settings.gmail_oauth_success_url, status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/gmail/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def gmail_disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    gmail: GmailClient = Depends(get_gmail_client),
) -> Response:
    connection = _connection(db, user)
    if connection is not None:
        cipher = get_token_cipher(settings)
        token = ""
        try:
            token = cipher.decrypt(connection.refresh_token_encrypted) or cipher.decrypt(connection.access_token_encrypted)
            gmail.revoke_token(token)
        except Exception:
            pass
        db.delete(connection)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/applications/{app_id}/gmail-draft", response_model=GmailDraftOut)
def create_or_update_gmail_draft(
    app_id: int,
    payload: GmailDraftRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    gmail: GmailClient = Depends(get_gmail_client),
) -> GmailDraftOut:
    app = _owned_app(db, user, app_id)
    connection = _connection(db, user)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connect Gmail before creating a draft.")

    to_email = (payload.to or app.recipient_email or "").strip()
    if payload.subject is not None:
        app.email_subject = payload.subject
    if payload.body is not None:
        app.email_body = payload.body
    subject = app.email_subject
    body = app.email_body
    if not to_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Add a recipient email before creating a Gmail draft.",
        )
    if not (subject or "").strip() or not (body or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Generate or provide an application email before creating a Gmail draft.",
        )

    profile = user.profile
    if profile is None:
        raise HTTPException(status_code=422, detail="Complete your profile before creating a Gmail draft.")
    try:
        packet_svc.sync_packet_documents(
            db=db,
            application=app,
            profile=profile,
            user_id=user.id,
            include_letter=bool((app.motivation_letter or "").strip()),
            include_email=True,
            storage=get_storage(),
        )
    except packet_svc.PacketError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    storage = get_storage()
    attachments: list[tuple[str, bytes, str]] = []
    if app.selected_cv_id:
        cv = db.get(CVVariant, app.selected_cv_id)
        if cv is not None and cv.user_id == user.id:
            try:
                attachments.append((f"CV_{packet_svc.slug(profile.name, 'CV')}.pdf", storage.get(cv.r2_key), cv.mime))
            except Exception:
                pass
    for doc in app.documents:
        if doc.kind == "motivation_letter":
            try:
                attachments.append((doc.filename, storage.get(doc.r2_key), doc.mime))
            except Exception:
                pass

    access_token = _access_token(db=db, connection=connection, gmail=gmail, settings=settings)
    raw = build_raw_message(
        from_email=connection.gmail_email,
        to=to_email,
        cc=payload.cc,
        bcc=payload.bcc,
        subject=subject,
        body=body,
        attachments=attachments,
    )

    try:
        if app.gmail_draft_id:
            result = gmail.update_draft(access_token, app.gmail_draft_id, raw)
        else:
            result = gmail.create_draft(access_token, raw)
    except GmailAPIError as exc:
        if not app.gmail_draft_id or exc.status_code != 404:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        result = gmail.create_draft(access_token, raw)

    app.gmail_draft_id = str(result.get("id") or app.gmail_draft_id)
    app.gmail_drafted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    return GmailDraftOut(
        gmail_draft_id=app.gmail_draft_id,
        to_email=to_email,
        subject=subject,
        gmail_drafted_at=app.gmail_drafted_at,
        application=app,
    )
