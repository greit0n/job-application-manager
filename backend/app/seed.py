"""Create or update a user and optional profile/CV data (idempotent by email).

    python -m app.seed --email georg@example.com --password "..." --name "Georg"

Run once per user (georg + girlfriend). Passwords are argon2-hashed; the plain
value is never stored.
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from sqlalchemy import select

from .auth import hash_password
from .db import SessionLocal
from .models import CVVariant, Profile, User
from .services.cv_text import extract_cv_text
from .services.storage import get_storage


def upsert_user(email: str, password: str, name: str) -> User:
    email = email.lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), display_name=name)
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            if name:
                user.display_name = name
            action = "updated"
        db.commit()
        db.refresh(user)
        print(f"User {email} {action} (id={user.id}).")
        return user


def upsert_profile(
    user_id: int,
    *,
    name: str = "",
    address: str = "",
    phone: str = "",
    email: str = "",
    languages: str = "",
    availability: str = "",
    preferences: str = "",
) -> None:
    values = {
        "name": name,
        "address": address,
        "phone": phone,
        "email": email,
        "languages": languages,
        "availability": availability,
        "preferences": preferences,
    }
    if not any(values.values()):
        return

    with SessionLocal() as db:
        profile = db.scalar(select(Profile).where(Profile.user_id == user_id))
        if profile is None:
            profile = Profile(user_id=user_id)
            db.add(profile)
            action = "created"
        else:
            action = "updated"

        for field, value in values.items():
            if value:
                setattr(profile, field, value)
        db.commit()
        db.refresh(profile)
        print(f"Profile {action} (id={profile.id}).")


def upsert_cv(
    user_id: int,
    *,
    label: str,
    language: str,
    notes: str,
    path: Path,
    is_default: bool = False,
) -> None:
    data = path.read_bytes()
    filename = path.name
    storage = get_storage()
    text = extract_cv_text(data, filename, ai=None)

    with SessionLocal() as db:
        if is_default:
            for other in db.scalars(select(CVVariant).where(CVVariant.user_id == user_id)):
                other.is_default = False

        cv = db.scalar(
            select(CVVariant).where(CVVariant.user_id == user_id, CVVariant.label == label)
        )
        if cv is None:
            key = f"{user_id}/cv/{uuid.uuid4().hex}_{filename}"
            cv = CVVariant(
                user_id=user_id,
                label=label,
                language=language,
                notes=notes,
                r2_key=key,
                filename=filename,
                mime="application/pdf",
                size=len(data),
                is_default=is_default,
                extracted_text=text,
            )
            db.add(cv)
            action = "created"
        else:
            key = cv.r2_key
            cv.language = language
            cv.notes = notes
            cv.filename = filename
            cv.mime = "application/pdf"
            cv.size = len(data)
            cv.is_default = is_default
            cv.extracted_text = text
            action = "updated"

        storage.put(key, data, content_type="application/pdf")
        db.commit()
        db.refresh(cv)
        print(f"CV '{label}' {action} (id={cv.id}, text={len(text)} chars).")


def parse_cv_spec(value: str) -> tuple[str, str, str, Path]:
    parts = value.split("|", 3)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "CV must use: label|language|notes|path"
        )
    label, language, notes, raw_path = parts
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"CV file does not exist: {path}")
    return label, language, notes, path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or update a user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--address", default="")
    parser.add_argument("--phone", default="")
    parser.add_argument("--languages", default="")
    parser.add_argument("--availability", default="")
    parser.add_argument("--preferences", default="")
    parser.add_argument(
        "--cv",
        action="append",
        type=parse_cv_spec,
        default=[],
        metavar="label|language|notes|path",
        help="Add/update a CV variant from a PDF. Can be passed multiple times.",
    )
    parser.add_argument(
        "--default-cv-label",
        default="",
        help="Label of the CV variant to mark as default.",
    )
    args = parser.parse_args()
    user = upsert_user(args.email, args.password, args.name)
    upsert_profile(
        user.id,
        name=args.name,
        address=args.address,
        phone=args.phone,
        email=args.email,
        languages=args.languages,
        availability=args.availability,
        preferences=args.preferences,
    )
    for label, language, notes, path in args.cv:
        upsert_cv(
            user.id,
            label=label,
            language=language,
            notes=notes,
            path=path,
            is_default=label == args.default_cv_label,
        )
