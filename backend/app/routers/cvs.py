"""CV variant management (upload / list / edit / delete / download)."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db
from ..downloads import download_response
from ..models import CVVariant, User
from ..schemas import CVOut, CVUpdate
from ..services.ai_client import get_ai_client
from ..services.cv_text import ensure_cv_text
from ..services.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cvs", tags=["cvs"])


def _owned_cv(db: Session, user: User, cv_id: int) -> CVVariant:
    cv = db.get(CVVariant, cv_id)
    if cv is None or cv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")
    return cv


@router.get("", response_model=list[CVOut])
def list_cvs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[CVVariant]:
    return list(
        db.scalars(
            select(CVVariant).where(CVVariant.user_id == user.id).order_by(CVVariant.created_at.desc())
        )
    )


@router.post("", response_model=CVOut, status_code=status.HTTP_201_CREATED)
async def upload_cv(
    file: UploadFile = File(...),
    label: str = Form(...),
    language: str = Form("de"),
    notes: str = Form(""),
    is_default: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CVVariant:
    data = await file.read()
    filename = Path(file.filename or "cv.pdf").name
    key = f"{user.id}/cv/{uuid.uuid4().hex}_{filename}"
    get_storage().put(key, data, content_type=file.content_type or "application/pdf")

    if is_default:
        for other in db.scalars(select(CVVariant).where(CVVariant.user_id == user.id)):
            other.is_default = False

    cv = CVVariant(
        user_id=user.id,
        label=label,
        language=language,
        notes=notes,
        r2_key=key,
        filename=filename,
        mime=file.content_type or "application/pdf",
        size=len(data),
        is_default=is_default,
    )
    db.add(cv)
    db.commit()
    db.refresh(cv)

    # Cache the CV's text now so generation can ground on it. Best-effort: a
    # failure here just leaves extracted_text empty; it is retried lazily at
    # generation time. Run off the event loop (blocking R2 + pdfplumber + CLI).
    try:
        await run_in_threadpool(
            ensure_cv_text,
            cv,
            db=db,
            storage=get_storage(),
            ai=get_ai_client(),
            timeout=get_settings().ai_timeout,
        )
    except Exception:
        logger.warning("CV text extraction on upload failed for cv_id=%s", cv.id, exc_info=True)
    db.refresh(cv)

    return cv


@router.patch("/{cv_id}", response_model=CVOut)
def update_cv(
    cv_id: int,
    payload: CVUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CVVariant:
    cv = _owned_cv(db, user, cv_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default"):
        for other in db.scalars(select(CVVariant).where(CVVariant.user_id == user.id)):
            other.is_default = False
    for field, value in data.items():
        setattr(cv, field, value)
    db.commit()
    db.refresh(cv)
    return cv


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cv(cv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    cv = _owned_cv(db, user, cv_id)
    try:
        get_storage().delete(cv.r2_key)
    except Exception:
        pass  # best-effort; remove the row regardless
    db.delete(cv)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{cv_id}/download")
def download_cv(cv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    cv = _owned_cv(db, user, cv_id)
    data = get_storage().get(cv.r2_key)
    return download_response(data=data, mime=cv.mime, filename=cv.filename)
