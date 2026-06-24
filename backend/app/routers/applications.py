"""Application CRUD (the tracker), scoped to the logged-in user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import STATUSES, Application, CVVariant, Profile, User
from ..schemas import ApplicationIn, ApplicationOut, ApplicationPacketUpdate, ApplicationUpdate
from ..services import packet as packet_svc
from ..services.storage import get_storage

router = APIRouter(prefix="/applications", tags=["applications"])


def _owned_app(db: Session, user: User, app_id: int) -> Application:
    app = db.get(Application, app_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return app


def _validate_status(value: str) -> None:
    if value not in STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status; expected one of {STATUSES}")


def _validate_selected_cv_id(db: Session, user: User, cv_id: int | None) -> None:
    if cv_id is None:
        return
    cv = db.get(CVVariant, cv_id)
    if cv is None or cv.user_id != user.id:
        raise HTTPException(status_code=422, detail="selected_cv_id not found")


def _get_or_create_profile(db: Session, user: User) -> Profile:
    if user.profile is not None:
        return user.profile
    profile = Profile(user_id=user.id)
    db.add(profile)
    db.flush()
    return profile


@router.get("", response_model=list[ApplicationOut])
def list_applications(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Application]:
    return list(
        db.scalars(
            select(Application)
            .where(Application.user_id == user.id)
            .order_by(Application.created_at.desc())
        )
    )


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Application:
    _validate_status(payload.status)
    _validate_selected_cv_id(db, user, payload.selected_cv_id)
    app = Application(user_id=user.id, **payload.model_dump())
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


@router.get("/{app_id}", response_model=ApplicationOut)
def get_application(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Application:
    return _owned_app(db, user, app_id)


@router.patch("/{app_id}", response_model=ApplicationOut)
def update_application(
    app_id: int,
    payload: ApplicationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Application:
    app = _owned_app(db, user, app_id)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        _validate_status(data["status"])
    if "selected_cv_id" in data:
        _validate_selected_cv_id(db, user, data["selected_cv_id"])
    for field, value in data.items():
        setattr(app, field, value)
    db.commit()
    db.refresh(app)
    return app


@router.put("/{app_id}/packet", response_model=ApplicationOut)
def update_application_packet(
    app_id: int,
    payload: ApplicationPacketUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Application:
    app = _owned_app(db, user, app_id)
    data = payload.model_dump(exclude_unset=True)

    if "language" in data and data["language"] is not None:
        if data["language"] not in ("de", "en"):
            raise HTTPException(status_code=422, detail="Invalid language; expected de or en")
        app.language = data["language"]

    for field in ("motivation_letter", "email_subject", "email_body"):
        if field in data and data[field] is not None:
            setattr(app, field, data[field])

    profile = _get_or_create_profile(db, user)
    if (app.motivation_letter or "").strip() and not (profile.name.strip() and profile.address.strip()):
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Complete your profile (name and address) before rendering a letter.",
        )

    try:
        packet_svc.sync_packet_documents(
            db=db,
            application=app,
            profile=profile,
            user_id=user.id,
            include_letter=True,
            include_email=True,
        )
    except packet_svc.PacketRenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except packet_svc.PacketStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return app


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    app = _owned_app(db, user, app_id)
    storage = get_storage()
    for doc in app.documents:
        try:
            storage.delete(doc.r2_key)
        except Exception:
            pass
    db.delete(app)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
