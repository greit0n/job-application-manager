"""The logged-in user's profile (one per user). Drives letter generation."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Profile, User
from ..schemas import ProfileIn, ProfileOut

router = APIRouter(prefix="/profile", tags=["profile"])


def _get_or_create(db: Session, user: User) -> Profile:
    if user.profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    return user.profile


@router.get("", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Profile:
    return _get_or_create(db, user)


@router.put("", response_model=ProfileOut)
def put_profile(
    payload: ProfileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Profile:
    profile = _get_or_create(db, user)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile
