"""Generation prompt assembly + call for the job-application manager.

This is the heart of the product: it turns a candidate profile + a job posting
into a per-job Motivationsschreiben (cover letter) and a (shorter) application
email, plus a recommendation for which CV variant fits.

Everything the model writes must be grounded ONLY in the supplied profile -- it
must never invent experience, employers, education, credentials or
compensation, and it must never mention AMS or that the candidate was told to
apply. German output uses the formal "Sie" and REAL umlauts (a o u s -> the
actual characters). Output is strict minified JSON; see `generate`.

Pure module: no FastAPI, no DB writes, no network beyond the injected `ai`.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from .ai_client import AIError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import Application, CVVariant, Profile


class GenerationError(RuntimeError):
    """Raised when generation fails (AI error or unusable response)."""


# --------------------------------------------------------------------------- #
# Dash sanitizing
# --------------------------------------------------------------------------- #
# Replace em dash, en dash, figure dash, horizontal bar, minus sign and the
# "--" double hyphen with a single ASCII hyphen. The document rules forbid
# anything but a single hyphen.
_DASH_CHARS = "‒–—―−"  # figure, en, em, horizontal bar, minus
_DASH_RE = re.compile(rf"\s*[{_DASH_CHARS}]\s*|\s*--+\s*")


def sanitize_dashes(text: str) -> str:
    """Collapse em/en dashes and double hyphens to a single spaced hyphen."""
    if not text:
        return ""
    out = _DASH_RE.sub(" - ", text)
    return out


def _s(value: Any) -> str:
    """Coerce to a clean string."""
    if value is None:
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #

def _format_cvs(cvs: Any) -> tuple[str, list[str]]:
    """Render CV variants (label + notes + full text) for the prompt.

    The text grounds the letter's experience claims; the labels are the menu the
    model recommends from. Returns (text, labels).
    """
    labels: list[str] = []
    if not cvs:
        return "(no CV variants on file - recommend nothing)", labels
    blocks: list[str] = []
    for cv in cvs:
        label = _s(getattr(cv, "label", ""))
        if not label:
            continue
        labels.append(label)
        lang = _s(getattr(cv, "language", ""))
        notes = _s(getattr(cv, "notes", "")) or "(no notes)"
        text = _s(getattr(cv, "extracted_text", "")) or "(no text extracted from this CV)"
        lang_part = f" [language: {lang}]" if lang else ""
        blocks.append(
            f'--- CV "{label}"{lang_part} - when to use: {notes} ---\n{text}'
        )
    if not blocks:
        return "(no CV variants on file - recommend nothing)", labels
    return "\n\n".join(blocks), labels


def _profile_block(profile: Any) -> str:
    fields = [
        ("Name", _s(getattr(profile, "name", ""))),
        ("Address", _s(getattr(profile, "address", ""))),
        ("Phone", _s(getattr(profile, "phone", ""))),
        ("Email", _s(getattr(profile, "email", ""))),
        ("Languages", _s(getattr(profile, "languages", ""))),
        ("Availability", _s(getattr(profile, "availability", ""))),
        ("Preferences", _s(getattr(profile, "preferences", ""))),
    ]
    return "\n".join(f"{k}: {v}" for k, v in fields if v) or "(no profile data)"


def _system_prompt(language: str) -> str:
    de = language == "de"
    salutation_rule = (
        'Use the formal German "Sie" throughout. Use REAL German umlauts '
        "(the actual characters a-umlaut, o-umlaut, u-umlaut and the sharp s) - "
        "NEVER transliterate them to ae/oe/ue/ss."
        if de
        else "Write in natural, professional English."
    )
    close_rule = (
        'The letter must end with "Mit freundlichen Gruessen" '
        "(written with the real umlaut: Grüßen) on its own line, "
        "followed by the candidate's full name."
        if de
        else 'The letter must end with "Kind regards" on its own line, '
        "followed by the candidate's full name."
    )
    subject_rule = (
        'The email subject is exactly "Bewerbung als <Position>".'
        if de
        else 'The email subject is exactly "Application for <Position>".'
    )
    return "\n".join(
        [
            "You are an expert career writer producing job-application documents for a "
            "single named candidate. You write each Motivationsschreiben (cover letter) "
            "freshly for the specific job - never from a template.",
            "",
            "GROUNDING RULES (absolute):",
            "- The candidate's CV(s), reproduced in full below, are your ONLY source for "
            "experience, employers, job titles, education, certifications, credentials and "
            "skills. NEVER invent anything beyond them. If the candidate lacks something the "
            "job wants, frame the gap honestly (e.g. conceptually familiar, would formally "
            "build it up) instead of fabricating.",
            "- NEVER mention 'AMS', a job centre, or that the candidate was told, required "
            "or advised to apply. Always frame the application as genuine personal interest.",
            "- If you cannot tell where the posting was found, refer to it neutrally "
            "(German: 'Ihre Ausschreibung') without naming a source.",
            "",
            "LETTER CRAFT - follow this narrative arc:",
            "1. Open with genuine, specific interest in this company/role and bridge from "
            "the job's concrete requirements to the candidate's REAL experience.",
            "2. Develop with concrete experience at the candidate's actual employers (drawn "
            "from the CV text), tying achievements to what the job needs.",
            "3. Close with an enthusiastic, company-specific paragraph.",
            "The letter MUST contain its own salutation at the top and its own closing - "
            "the PDF renderer adds only the sender block, date and subject around your text.",
            f"- {salutation_rule}",
            f"- {close_rule}",
            "",
            "EMAIL: shorter than the letter (the letter PDF carries the detail) - a brief, "
            "warm note referencing the attached application documents.",
            f"- {subject_rule}",
            "",
            "FORMATTING (strict): Use a SINGLE hyphen only. NEVER use em dashes, en dashes "
            "or double dashes. Left-align everything - NEVER justify. No markdown, no "
            "bullet characters inside the letter body.",
            "",
            "CV RECOMMENDATION: from the provided CV variants, pick the single label that "
            "best fits this job and explain briefly why. The recommended label MUST be one "
            "of the provided labels exactly, or empty if none were provided.",
            "",
            "OUTPUT: Return STRICT minified JSON with EXACTLY these keys and nothing else "
            "(no prose, no markdown fences):",
            '{"extracted":{"company":"","position":"","location":"","salary":"",'
            '"deadline":"","requirements":[]},"recommended_cv_label":"",'
            '"recommended_cv_reason":"","motivation_letter":"","email_subject":"",'
            '"email_body":""}',
            "Honor the requested outputs: if a letter is not requested, motivation_letter "
            'must be ""; if an email is not requested, email_subject and email_body must '
            'both be "".',
        ]
    )


def build_messages(
    *,
    profile: Any,
    application: Any,
    cvs: Any,
    language: str,
    produce_letter: bool,
    produce_email: bool,
    extra: str = "",
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt).

    `profile` and `application` are ORM objects (attributes accessed directly);
    `cvs` is a list of CVVariant ORM objects.
    """
    language = (language or "de").lower()
    if language not in ("de", "en"):
        language = "de"

    system = _system_prompt(language)

    profile_block = _profile_block(profile)
    cv_block, _labels = _format_cvs(cvs)

    company = _s(getattr(application, "company", ""))
    position = _s(getattr(application, "position", ""))
    job_text = _s(getattr(application, "job_text", ""))
    app_location = _s(getattr(application, "location", ""))
    app_salary = _s(getattr(application, "salary", ""))
    app_url = _s(getattr(application, "url", ""))

    if job_text:
        posting_section = job_text
    else:
        posting_section = (
            "(No posting text was supplied. Rely on the company / position fields "
            "below and keep claims about the role conservative.)"
        )

    known_bits = []
    if company:
        known_bits.append(f"Company: {company}")
    if position:
        known_bits.append(f"Position: {position}")
    if app_location:
        known_bits.append(f"Location: {app_location}")
    if app_salary:
        known_bits.append(f"Salary (as recorded): {app_salary}")
    if app_url:
        known_bits.append(f"Source URL: {app_url}")
    known_block = "\n".join(known_bits) if known_bits else "(none recorded)"

    lang_name = "German (de)" if language == "de" else "English (en)"

    outputs: list[str] = []
    if produce_letter:
        outputs.append(
            "- motivation_letter: write the full cover letter (with salutation and "
            "closing + the candidate name)."
        )
    else:
        outputs.append('- motivation_letter: leave it as "" (not requested).')
    if produce_email:
        outputs.append(
            "- email_subject and email_body: write a SHORT application email "
            "(shorter than the letter)."
        )
    else:
        outputs.append(
            '- email_subject and email_body: leave both as "" (not requested).'
        )

    extra_block = (
        f"\nEXTRA INSTRUCTIONS FROM THE USER (follow these):\n{_s(extra)}\n"
        if _s(extra)
        else ""
    )

    user = "\n".join(
        [
            f"TARGET OUTPUT LANGUAGE: {lang_name}. Write all generated documents in this language.",
            "",
            "=== CANDIDATE PROFILE ===",
            profile_block,
            "",
            "=== KNOWN APPLICATION FACTS ===",
            known_block,
            "",
            "=== JOB POSTING TEXT ===",
            posting_section,
            "",
            "=== CANDIDATE CVs (full text - your ONLY source for real experience; also recommend the best-fitting label) ===",
            cv_block,
            extra_block,
            "=== WHAT TO PRODUCE ===",
            "Also fill the 'extracted' object from the posting (company, position, "
            "location, salary, deadline, and a 'requirements' list of the key "
            "requirements). Use \"\" / [] for anything not present.",
            *outputs,
            "",
            "Return ONLY the strict minified JSON object described in the system prompt.",
        ]
    )

    return system, user


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def _norm_str(value: Any) -> str:
    return sanitize_dashes(_s(value))


def _norm_requirements(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        # e.g. {"must":[...],"nice":[...]} - flatten list values, keep scalars.
        items = []
        for v in value.values():
            if isinstance(v, list):
                items.extend(v)
            elif v:
                items.append(v)
    elif value in (None, ""):
        items = []
    else:
        # A single string or other scalar; split on newlines if it looks listy.
        text = _s(value)
        items = [p for p in re.split(r"[\n;]+", text) if p.strip()] if text else []
    for item in items:
        s = _norm_str(item)
        if s:
            out.append(s)
    return out


def _normalize(
    raw: Any,
    *,
    cv_labels: list[str],
    produce_letter: bool,
    produce_email: bool,
) -> dict:
    if not isinstance(raw, dict):
        raw = {}

    ext_raw = raw.get("extracted")
    if not isinstance(ext_raw, dict):
        ext_raw = {}
    extracted = {
        "company": _norm_str(ext_raw.get("company")),
        "position": _norm_str(ext_raw.get("position")),
        "location": _norm_str(ext_raw.get("location")),
        "salary": _norm_str(ext_raw.get("salary")),
        "deadline": _norm_str(ext_raw.get("deadline")),
        "requirements": _norm_requirements(ext_raw.get("requirements")),
    }

    # CV recommendation must be one of the provided labels (case-insensitive
    # match), else "".
    rec_label = _s(raw.get("recommended_cv_label"))
    matched = ""
    if rec_label and cv_labels:
        for label in cv_labels:
            if label.lower() == rec_label.lower():
                matched = label
                break
    recommended_cv_reason = _norm_str(raw.get("recommended_cv_reason"))
    if not matched:
        # Keep a reason only meaningful if we have a label; otherwise drop it.
        if not cv_labels:
            recommended_cv_reason = recommended_cv_reason

    letter = _norm_str(raw.get("motivation_letter")) if produce_letter else ""
    email_subject = _norm_str(raw.get("email_subject")) if produce_email else ""
    email_body = _norm_str(raw.get("email_body")) if produce_email else ""

    return {
        "extracted": extracted,
        "recommended_cv_label": matched,
        "recommended_cv_reason": recommended_cv_reason,
        "motivation_letter": letter,
        "email_subject": email_subject,
        "email_body": email_body,
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def generate(
    ai: Any,
    *,
    profile: Any,
    application: Any,
    cvs: Any,
    language: str = "de",
    produce_letter: bool = True,
    produce_email: bool = True,
    extra: str = "",
    timeout: int | None = None,
) -> dict:
    """Assemble the prompt, call the AI, and normalize the JSON result.

    Wraps AI errors / bad JSON in `GenerationError`.
    """
    system, user = build_messages(
        profile=profile,
        application=application,
        cvs=cvs,
        language=language,
        produce_letter=produce_letter,
        produce_email=produce_email,
        extra=extra,
    )

    _, cv_labels = _format_cvs(cvs)

    try:
        raw = ai.complete_json(user, system=system, timeout=timeout)
    except AIError as exc:
        raise GenerationError(f"AI generation failed: {exc}") from exc
    except (json.JSONDecodeError, ValueError) as exc:  # pragma: no cover - defensive
        raise GenerationError(f"AI returned unusable JSON: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise GenerationError(f"Unexpected generation failure: {exc}") from exc

    return _normalize(
        raw,
        cv_labels=cv_labels,
        produce_letter=produce_letter,
        produce_email=produce_email,
    )
