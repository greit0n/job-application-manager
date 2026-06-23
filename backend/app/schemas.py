"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ─── Auth ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: int
    email: str
    display_name: str


# ─── Profile ───────────────────────────────────────────────────────
class ProfileIn(BaseModel):
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    languages: str = ""
    availability: str = ""
    preferences: str = ""


class ProfileOut(ProfileIn, ORMModel):
    id: int
    updated_at: datetime | None = None


# ─── CV variants ───────────────────────────────────────────────────
class CVOut(ORMModel):
    id: int
    label: str
    language: str
    notes: str
    filename: str
    mime: str
    size: int
    is_default: bool
    created_at: datetime | None = None


class CVUpdate(BaseModel):
    label: str | None = None
    language: str | None = None
    notes: str | None = None
    is_default: bool | None = None


# ─── Applications ──────────────────────────────────────────────────
class ApplicationIn(BaseModel):
    company: str = ""
    position: str = ""
    status: str = "pending"
    language: str = "de"
    source: str = ""
    salary: str = ""
    location: str = ""
    url: str = ""
    deadline: date | None = None
    notes: str = ""
    selected_cv_id: int | None = None
    job_text: str = ""


class ApplicationUpdate(BaseModel):
    company: str | None = None
    position: str | None = None
    status: str | None = None
    language: str | None = None
    source: str | None = None
    salary: str | None = None
    location: str | None = None
    url: str | None = None
    deadline: date | None = None
    notes: str | None = None
    selected_cv_id: int | None = None
    job_text: str | None = None
    motivation_letter: str | None = None
    email_subject: str | None = None
    email_body: str | None = None


class DocumentOut(ORMModel):
    id: int
    kind: str
    filename: str
    mime: str
    size: int
    created_at: datetime | None = None


# ─── Intake & AI generation ────────────────────────────────────────
class IntakeRequest(BaseModel):
    """JSON intake (paste text or URL). File uploads use multipart instead."""

    mode: str = "paste"            # paste | url
    text: str = ""
    url: str = ""
    language: str = "de"
    company: str = ""
    position: str = ""


class GenerateRequest(BaseModel):
    """Ask the AI to (re)generate documents for an existing application."""

    language: str = "de"           # de | en
    produce_letter: bool = True
    produce_email: bool = True
    cv_id: int | None = None       # manual CV override; None = let the AI recommend
    extra_instructions: str = ""


class ApplicationOut(ORMModel):
    id: int
    company: str
    position: str
    status: str
    language: str
    source: str
    salary: str
    location: str
    url: str
    deadline: date | None = None
    notes: str
    selected_cv_id: int | None = None
    job_text: str
    extracted: dict
    motivation_letter: str
    email_subject: str
    email_body: str
    cv_recommendation: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    documents: list[DocumentOut] = Field(default_factory=list)
