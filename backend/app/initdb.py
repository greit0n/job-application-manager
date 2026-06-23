"""Create all tables (dev convenience). Prod uses Alembic migrations.

    python -m app.initdb
"""
from __future__ import annotations

from . import models  # noqa: F401  (register models on Base)
from .db import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables created.")


if __name__ == "__main__":
    init_db()
