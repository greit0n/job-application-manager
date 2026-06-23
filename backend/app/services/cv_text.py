"""Extract and cache the text of an uploaded CV for grounding generation.

A CV PDF exported from Word has a text layer (pdfplumber reads it). A scanned /
image-only PDF has none, so we fall back to AI transcription (the same path the
job-posting image intake uses). The result is cached on `CVVariant.extracted_text`
so we extract once and reuse it on every generation.

Pure of FastAPI; the DB session, storage and AI client are all injected.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import intake as intake_svc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import CVVariant


def extract_cv_text(
    data: bytes, filename: str, ai: Any, *, timeout: int | None = None
) -> str:
    """Return the CV's text. pdfplumber first, AI-transcription fallback.

    Never raises: returns "" if nothing usable could be extracted (e.g. no text
    layer and no AI backend available).
    """
    if not data:
        return ""
    try:
        return intake_svc.extract_pdf_text(data)
    except intake_svc.IntakeError:
        pass
    if ai is None:
        return ""
    try:
        return intake_svc.extract_image_text(data, filename, ai, timeout=timeout)
    except intake_svc.IntakeError:
        return ""
    except Exception:
        return ""


def ensure_cv_text(
    cv: "CVVariant",
    *,
    db: Any,
    storage: Any,
    ai: Any,
    timeout: int | None = None,
) -> str:
    """Populate cv.extracted_text from R2 if empty; persist and return it.

    Best-effort: a storage or extraction failure leaves the text empty and does
    not raise, so uploads and generation are never blocked by it.
    """
    if (cv.extracted_text or "").strip():
        return cv.extracted_text
    try:
        data = storage.get(cv.r2_key)
    except Exception:
        return cv.extracted_text or ""
    text = extract_cv_text(data, cv.filename, ai, timeout=timeout)
    if text:
        cv.extracted_text = text
        db.commit()
    return cv.extracted_text or ""
