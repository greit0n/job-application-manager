"""Create or update a user (idempotent by email).

    python -m app.seed --email georg@example.com --password "..." --name "Georg"

Run once per user (georg + girlfriend). Passwords are argon2-hashed; the plain
value is never stored.
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from .auth import hash_password
from .db import SessionLocal
from .models import User


def upsert_user(email: str, password: str, name: str) -> None:
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
        print(f"User {email} {action} (id={user.id}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or update a user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    upsert_user(args.email, args.password, args.name)
