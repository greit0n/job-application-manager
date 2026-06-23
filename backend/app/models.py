"""SQLAlchemy ORM models.

Every row that holds user data carries a `user_id` so queries can be scoped to
the logged-in user (georg and his girlfriend never see each other's data).
Files (CVs, postings, generated PDFs, ZIPs) live in R2; only metadata is here.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Application pipeline. Keys match the original app; the frontend maps to
# bilingual labels (Beworben / Vorstellungsgespräch / ...).
STATUSES = ["pending", "applied", "interview", "offer", "rejected", "filled"]

# Document kinds attached to an application.
DOC_KINDS = ["posting", "cv", "motivation_letter", "email", "zip", "proof"]

LANGUAGES = ["de", "en"]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    cv_variants: Mapped[list["CVVariant"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    """One per user. Drives every generated letter/email — real data only."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)

    name: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    headline: Mapped[str] = mapped_column(String(255), default="")
    languages: Mapped[str] = mapped_column(String(255), default="")
    availability: Mapped[str] = mapped_column(String(255), default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    preferences: Mapped[str] = mapped_column(Text, default="")
    # [{name, role, start, end, highlights:[...]}, ...] used to ground letters.
    employers: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")


class CVVariant(Base):
    __tablename__ = "cv_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    label: Mapped[str] = mapped_column(String(120))            # e.g. "Fullstack", "Leadership"
    language: Mapped[str] = mapped_column(String(8), default="de")
    notes: Mapped[str] = mapped_column(Text, default="")        # when to use this variant
    r2_key: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120), default="application/pdf")
    size: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="cv_variants")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    company: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    language: Mapped[str] = mapped_column(String(8), default="de")
    source: Mapped[str] = mapped_column(String(255), default="")
    salary: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    selected_cv_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_variants.id", ondelete="SET NULL"), nullable=True
    )

    # Normalized job text + AI-extracted structure (filled by intake/generation).
    job_text: Mapped[str] = mapped_column(Text, default="")
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)

    # Latest generated content (rendered files live in `documents`).
    motivation_letter: Mapped[str] = mapped_column(Text, default="")
    email_subject: Mapped[str] = mapped_column(String(255), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    cv_recommendation: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="applications")
    selected_cv: Mapped["CVVariant | None"] = relationship()
    documents: Mapped[list["Document"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    kind: Mapped[str] = mapped_column(String(32))   # see DOC_KINDS
    r2_key: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped["Application"] = relationship(back_populates="documents")


class Generation(Base):
    """Audit trail for each AI generation attempt."""

    __tablename__ = "generations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    kind: Mapped[str] = mapped_column(String(32))       # letter | email | full
    language: Mapped[str] = mapped_column(String(8), default="de")
    model: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | error
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
