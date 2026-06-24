"""AI-driven intake, document generation, and ZIP bundling.

All endpoints are scoped to the logged-in user. The AI client is injected via the
`get_ai` dependency so tests can override it with a fake.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import Application, CVVariant, Document, Generation, Profile, User
from ..schemas import ApplicationOut, DocumentOut, GenerateRequest
from ..services import bundle as bundle_svc
from ..services import generation as gen_svc
from ..services import intake as intake_svc
from ..services import packet as packet_svc
from ..services.ai_client import AIClient, get_ai_client
from ..services.cv_text import ensure_cv_text
from ..services.storage import get_storage

router = APIRouter(prefix="/applications", tags=["ai"])


def get_ai() -> AIClient:
    """Dependency wrapper so tests can override the AI backend."""
    return get_ai_client()


def _owned_app(db: Session, user: User, app_id: int) -> Application:
    app = db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return app


def _get_or_create_profile(db: Session, user: User) -> Profile:
    if user.profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    return user.profile


def _parse_deadline(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


# Intake: paste / URL / upload to a draft application.
@router.post("/intake", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def intake_application(
    mode: str = Form("paste"),
    text: str = Form(""),
    url: str = Form(""),
    language: str = Form("de"),
    company: str = Form(""),
    position: str = Form(""),
    file: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIClient = Depends(get_ai),
) -> Application:
    file_bytes = await file.read() if file is not None else None
    filename = Path(file.filename or "posting").name if file is not None else ""
    content_type = (file.content_type if file is not None else "") or ""

    try:
        # intake does blocking I/O (httpx / pdfplumber / Claude subprocess); run it
        # off the event loop so other users' requests are not frozen.
        job_text = await run_in_threadpool(
            intake_svc.intake,
            mode=mode,
            text=text,
            url=url,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            ai=ai,
            timeout=get_settings().claude_timeout,
        )
    except intake_svc.IntakeError as exc:
        # An uploaded posting is still worth keeping even if text extraction fails;
        # for paste/URL with no usable text there is nothing to store, so 422.
        if file_bytes is None:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        job_text = ""

    source = {
        "paste": "Pasted text",
        "url": url or "URL",
        "upload": filename or "Uploaded posting",
    }.get(mode, mode)

    app = Application(
        user_id=user.id,
        company=company,
        position=position,
        language=language if language in ("de", "en") else "de",
        status="pending",
        source=source,
        url=url,
        job_text=job_text,
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    if file_bytes is not None:
        key = f"{user.id}/app-{app.id}/posting/{uuid.uuid4().hex}_{filename}"
        get_storage().put(key, file_bytes, content_type=content_type or "application/octet-stream")
        db.add(
            Document(
                application_id=app.id,
                user_id=user.id,
                kind="posting",
                r2_key=key,
                filename=filename,
                mime=content_type or "application/octet-stream",
                size=len(file_bytes),
            )
        )
        db.commit()
        db.refresh(app)

    return app


# Generate: AI writes the letter/email, picks the CV, renders PDFs.
@router.post("/{app_id}/generate", response_model=ApplicationOut)
def generate_documents(
    app_id: int,
    payload: GenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIClient = Depends(get_ai),
) -> Application:
    app = _owned_app(db, user, app_id)
    profile = _get_or_create_profile(db, user)
    cvs = list(db.scalars(select(CVVariant).where(CVVariant.user_id == user.id)))
    language = payload.language if payload.language in ("de", "en") else (app.language or "de")

    # A letter needs a real sender block (name + address). The UI forces profile
    # completion on first login; this guards direct API calls.
    if payload.produce_letter and not (profile.name.strip() and profile.address.strip()):
        raise HTTPException(
            status_code=422,
            detail="Complete your profile (name and address) before generating a letter.",
        )

    # Lazily backfill CV text for any variant uploaded before extraction existed
    # (self-healing) so grounding has the real experience to draw on.
    storage = get_storage()
    for cv in cvs:
        if not (cv.extracted_text or "").strip():
            ensure_cv_text(
                cv,
                db=db,
                storage=storage,
                ai=ai,
                timeout=get_settings().claude_timeout,
            )

    # Generation grounds entirely on CV text now - refuse if there is none.
    if (payload.produce_letter or payload.produce_email) and not any(
        (cv.extracted_text or "").strip() for cv in cvs
    ):
        raise HTTPException(
            status_code=422,
            detail="Upload a CV with readable text before generating documents.",
        )

    try:
        result = gen_svc.generate(
            ai,
            profile=profile,
            application=app,
            cvs=cvs,
            language=language,
            produce_letter=payload.produce_letter,
            produce_email=payload.produce_email,
            extra=payload.extra_instructions,
            timeout=get_settings().claude_timeout,
        )
    except gen_svc.GenerationError as exc:
        db.add(
            Generation(
                application_id=app.id,
                user_id=user.id,
                kind="full",
                language=language,
                status="error",
                error=str(exc)[:2000],
            )
        )
        db.commit()
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}") from exc

    extracted = result.get("extracted") or {}
    app.language = language
    app.extracted = extracted
    app.cv_recommendation = result.get("recommended_cv_reason", "") or ""
    if payload.produce_letter:
        app.motivation_letter = result.get("motivation_letter", "") or ""
    if payload.produce_email:
        app.email_subject = result.get("email_subject", "") or ""
        app.email_body = result.get("email_body", "") or ""

    # Backfill empty application fields from what the AI extracted.
    if not app.company and extracted.get("company"):
        app.company = extracted["company"]
    if not app.position and extracted.get("position"):
        app.position = extracted["position"]
    if not app.location and extracted.get("location"):
        app.location = extracted["location"]
    if not app.salary and extracted.get("salary"):
        app.salary = extracted["salary"]
    if app.deadline is None:
        parsed = _parse_deadline(str(extracted.get("deadline", "")))
        if parsed is not None:
            app.deadline = parsed

    # CV selection: manual override wins, else the AI's recommendation by label.
    if payload.cv_id is not None:
        if not any(c.id == payload.cv_id for c in cvs):
            raise HTTPException(status_code=422, detail="cv_id not found")
        app.selected_cv_id = payload.cv_id
    elif result.get("recommended_cv_label"):
        wanted = result["recommended_cv_label"].strip().lower()
        match = next((c for c in cvs if c.label.strip().lower() == wanted), None)
        if match is not None:
            app.selected_cv_id = match.id

    def _audit_error(message: str) -> None:
        db.rollback()
        db.add(
            Generation(
                application_id=app.id,
                user_id=user.id,
                kind="full",
                language=language,
                model=get_settings().claude_model or "",
                status="error",
                error=message[:2000],
            )
        )
        db.commit()

    try:
        packet_svc.sync_packet_documents(
            db=db,
            application=app,
            profile=profile,
            user_id=user.id,
            include_letter=payload.produce_letter,
            include_email=payload.produce_email,
            storage=storage,
        )
    except packet_svc.PacketRenderError as exc:
        _audit_error(f"render failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Document rendering failed: {exc}") from exc
    except packet_svc.PacketStorageError as exc:
        _audit_error(f"storage failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Storing documents failed: {exc}") from exc

    db.add(
        Generation(
            application_id=app.id,
            user_id=user.id,
            kind="full",
            language=language,
            model=get_settings().claude_model or "",
            status="ok",
        )
    )
    db.commit()
    db.refresh(app)
    return app


# Bundle: CV + letter + email to a downloadable ZIP.
@router.post("/{app_id}/bundle", response_model=DocumentOut)
def bundle_documents(
    app_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    app = _owned_app(db, user, app_id)
    profile = _get_or_create_profile(db, user)
    storage = get_storage()

    selected_cv = None
    if app.selected_cv_id:
        cv = db.get(CVVariant, app.selected_cv_id)
        if cv is not None and cv.user_id == user.id:
            selected_cv = cv

    files = packet_svc.collect_bundle_files(
        application=app,
        profile=profile,
        storage=storage,
        selected_cv=selected_cv,
    )

    if not files:
        raise HTTPException(
            status_code=422,
            detail="Nothing to bundle yet - generate the documents or select a CV first.",
        )

    zip_bytes = bundle_svc.build_zip(files)

    for doc in list(app.documents):
        if doc.kind == "zip":
            try:
                storage.delete(doc.r2_key)
            except Exception:
                pass
            db.delete(doc)
    db.commit()

    fn = f"Application_{packet_svc.slug(app.company)}.zip"
    key = f"{user.id}/app-{app.id}/zip/{uuid.uuid4().hex}_{fn}"
    storage.put(key, zip_bytes, content_type="application/zip")
    doc = Document(
        application_id=app.id,
        user_id=user.id,
        kind="zip",
        r2_key=key,
        filename=fn,
        mime="application/zip",
        size=len(zip_bytes),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
