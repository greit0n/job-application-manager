"""Documents attached to an application (posting, cv, letter, email, zip, proof)."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..downloads import download_response
from ..models import DOC_KINDS, Application, Document, User
from ..schemas import DocumentOut
from ..services.storage import get_storage

router = APIRouter(tags=["documents"])


def _owned_app(db: Session, user: User, app_id: int) -> Application:
    app = db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return app


def _owned_doc(db: Session, user: User, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.get("/applications/{app_id}/documents", response_model=list[DocumentOut])
def list_documents(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Document]:
    _owned_app(db, user, app_id)
    return list(
        db.scalars(
            select(Document).where(Document.application_id == app_id).order_by(Document.created_at.asc())
        )
    )


@router.post("/applications/{app_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    app_id: int,
    file: UploadFile = File(...),
    kind: str = Form("proof"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    if kind not in DOC_KINDS:
        raise HTTPException(status_code=422, detail=f"Invalid kind; expected one of {DOC_KINDS}")
    _owned_app(db, user, app_id)
    data = await file.read()
    filename = Path(file.filename or "file").name
    key = f"{user.id}/app-{app_id}/{kind}/{uuid.uuid4().hex}_{filename}"
    get_storage().put(key, data, content_type=file.content_type or "application/octet-stream")
    doc = Document(
        application_id=app_id,
        user_id=user.id,
        kind=kind,
        r2_key=key,
        filename=filename,
        mime=file.content_type or "application/octet-stream",
        size=len(data),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    doc = _owned_doc(db, user, doc_id)
    data = get_storage().get(doc.r2_key)
    return download_response(data=data, mime=doc.mime, filename=doc.filename)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    doc = _owned_doc(db, user, doc_id)
    try:
        get_storage().delete(doc.r2_key)
    except Exception:
        pass
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
