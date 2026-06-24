"""Application packet document rendering and bundling helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import uuid

from sqlalchemy.orm import Session

from ..models import Application, CVVariant, Document, Profile
from . import pdf as pdf_svc
from .storage import Storage, get_storage

_DE_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
_PACKET_KINDS = {"motivation_letter", "email"}


class PacketError(Exception):
    """Base class for packet rendering/storage failures."""


class PacketRenderError(PacketError):
    """Raised when the current application fields cannot be rendered."""


class PacketStorageError(PacketError):
    """Raised when rendered packet files cannot be stored or persisted."""


@dataclass(frozen=True)
class PacketFile:
    kind: str
    data: bytes
    filename: str
    mime: str


def slug(value: str, fallback: str = "Application") -> str:
    cleaned = re.sub(r"[^\w\s-]", "", value or "", flags=re.UNICODE).strip()
    cleaned = re.sub(r"[\s]+", "_", cleaned)
    return cleaned or fallback


def format_date(language: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if language == "de":
        return f"{now.day}. {_DE_MONTHS[now.month - 1]} {now.year}"
    return now.strftime("%d %B %Y")


def email_text(application: Application) -> bytes:
    return (
        f"Subject: {application.email_subject or ''}\n\n"
        f"{application.email_body or ''}\n"
    ).encode("utf-8")


def render_packet_files(
    *,
    application: Application,
    profile: Profile,
    include_letter: bool = True,
    include_email: bool = True,
) -> list[PacketFile]:
    """Render current application packet fields to in-memory files."""
    language = application.language if application.language in ("de", "en") else "de"
    company_slug = slug(application.company)
    files: list[PacketFile] = []

    if include_letter and (application.motivation_letter or "").strip():
        sender = {
            "name": profile.name,
            "address": profile.address,
            "phone": profile.phone,
            "email": profile.email,
        }
        position = application.position or ""
        subject = application.email_subject or (
            f"Bewerbung als {position}" if language == "de" else f"Application for {position}"
        )
        try:
            pdf_bytes = pdf_svc.render_letter_pdf(
                sender=sender,
                subject=subject,
                body=application.motivation_letter,
                date_str=format_date(language),
                language=language,
            )
        except Exception as exc:
            raise PacketRenderError(f"Document rendering failed: {exc}") from exc
        files.append(
            PacketFile(
                kind="motivation_letter",
                data=pdf_bytes,
                filename=f"Motivationsschreiben_{company_slug}.pdf",
                mime="application/pdf",
            )
        )

    if include_email and (
        (application.email_subject or "").strip() or (application.email_body or "").strip()
    ):
        files.append(
            PacketFile(
                kind="email",
                data=email_text(application),
                filename=f"Email_{company_slug}.txt",
                mime="text/plain; charset=utf-8",
            )
        )

    return files


def sync_packet_documents(
    *,
    db: Session,
    application: Application,
    profile: Profile,
    user_id: int,
    include_letter: bool = True,
    include_email: bool = True,
    storage: Storage | None = None,
) -> None:
    """Replace rendered packet documents with all-or-nothing DB semantics.

    New files are rendered and uploaded before existing rows are removed. If any
    render, upload, or commit step fails, the database transaction is rolled back
    and any newly uploaded objects are deleted best-effort.
    """
    storage = storage or get_storage()
    replace_kinds: set[str] = set()
    if include_letter:
        replace_kinds.add("motivation_letter")
    if include_email:
        replace_kinds.add("email")

    try:
        files = render_packet_files(
            application=application,
            profile=profile,
            include_letter=include_letter,
            include_email=include_email,
        )
    except PacketRenderError:
        db.rollback()
        raise

    stored: list[tuple[PacketFile, str]] = []
    try:
        for file in files:
            key = f"{user_id}/app-{application.id}/{file.kind}/{uuid.uuid4().hex}_{file.filename}"
            storage.put(key, file.data, content_type=file.mime)
            stored.append((file, key))
    except Exception as exc:
        for _, key in stored:
            try:
                storage.delete(key)
            except Exception:
                pass
        db.rollback()
        raise PacketStorageError(f"Storing documents failed: {exc}") from exc

    previous = [doc for doc in list(application.documents) if doc.kind in replace_kinds]
    try:
        for doc in previous:
            db.delete(doc)
        for file, key in stored:
            db.add(
                Document(
                    application_id=application.id,
                    user_id=user_id,
                    kind=file.kind,
                    r2_key=key,
                    filename=file.filename,
                    mime=file.mime,
                    size=len(file.data),
                )
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        for _, key in stored:
            try:
                storage.delete(key)
            except Exception:
                pass
        raise PacketStorageError(f"Persisting documents failed: {exc}") from exc

    for doc in previous:
        try:
            storage.delete(doc.r2_key)
        except Exception:
            pass
    db.refresh(application)


def collect_bundle_files(
    *,
    application: Application,
    profile: Profile,
    storage: Storage | None = None,
    selected_cv: CVVariant | None = None,
) -> list[tuple[str, bytes]]:
    """Collect current CV and rendered packet files for ZIP bundling."""
    storage = storage or get_storage()
    files: list[tuple[str, bytes]] = []

    if selected_cv is not None and selected_cv.user_id == application.user_id:
        try:
            files.append((f"CV_{slug(profile.name, 'CV')}.pdf", storage.get(selected_cv.r2_key)))
        except Exception:
            pass

    for doc in application.documents:
        if doc.kind in _PACKET_KINDS:
            try:
                files.append((doc.filename, storage.get(doc.r2_key)))
            except Exception:
                pass

    return files
