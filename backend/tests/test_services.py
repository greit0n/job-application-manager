"""Offline, deterministic tests for the new service modules.

These modules (pdf, bundle, generation, intake) are written concurrently by
other agents to the contracts documented in the task. Tests use no network,
no real AI, and no DB. A fake AI object stands in for AIClient.
"""

from __future__ import annotations

import io
import types
import zipfile

import pytest

# ---------------------------------------------------------------------------
# Fake AI (do NOT import the real AIClient ABC).
# ---------------------------------------------------------------------------


class FakeAI:
    """Minimal stand-in for AIClient with deterministic, configurable output."""

    def __init__(self, json_result=None, raise_exc: BaseException | None = None):
        self._json_result = json_result if json_result is not None else {}
        self._raise = raise_exc
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, files=None, timeout=None):
        self.calls.append({"prompt": prompt, "system": system, "files": files})
        if self._raise is not None:
            raise self._raise
        return "fake text"

    def complete_json(self, prompt, *, system=None, files=None, timeout=None, schema=None):
        self.calls.append(
            {"prompt": prompt, "system": system, "files": files, "schema": schema}
        )
        if self._raise is not None:
            raise self._raise
        return dict(self._json_result)


# ---------------------------------------------------------------------------
# Fixtures: fake ORM-like objects via SimpleNamespace.
# ---------------------------------------------------------------------------


def make_profile():
    return types.SimpleNamespace(
        name="Georg Damyanov",
        address="Musterstrasse 1, 1010 Wien",
        phone="+43 660 1234567",
        email="georg@example.com",
        headline="Fullstack Developer",
        languages="Deutsch (Muttersprache), Englisch (fliessend)",
        availability="ab sofort",
        skills="Python, FastAPI, SQLAlchemy, React",
        summary="Erfahrener Entwickler mit Fokus auf Webanwendungen.",
        preferences="Remote bevorzugt",
        employers=[
            {
                "name": "Litenweb GmbH",
                "role": "Senior Developer",
                "start": "2020",
                "end": "2024",
                "highlights": ["Backend-Architektur", "Team-Leitung"],
            }
        ],
    )


def make_application(language="de"):
    return types.SimpleNamespace(
        id=1,
        company="ACME AG",
        position="Backend Engineer",
        status="draft",
        language=language,
        source="paste",
        salary=None,
        location="Wien",
        url=None,
        deadline=None,
        notes="",
        selected_cv_id=None,
        job_text="Wir suchen einen Backend Engineer mit Python-Erfahrung.",
        extracted={},
        motivation_letter=None,
        email_subject=None,
        email_body=None,
        cv_recommendation=None,
    )


def make_cvs():
    return [
        types.SimpleNamespace(
            id=10, label="Fullstack", language="de",
            notes="Fuer breite Rollen", filename="cv_fullstack.pdf", is_default=True,
            extracted_text="Senior Developer at Litenweb GmbH since 2020.",
        ),
        types.SimpleNamespace(
            id=11, label="Leadership", language="de",
            notes="Fuer Fuehrungsrollen", filename="cv_leadership.pdf", is_default=False,
            extracted_text="Tech Lead at Litenweb GmbH, 2022-2024.",
        ),
    ]


# ---------------------------------------------------------------------------
# 1 & 2. pdf module
# ---------------------------------------------------------------------------


def test_sanitize_replaces_dashes_with_hyphen():
    pdf = pytest.importorskip("app.services.pdf", reason="pdf service not yet available")
    text = "alpha—beta – gamma -- delta"
    out = pdf.sanitize(text)
    assert "—" not in out  # em dash gone
    assert "–" not in out  # en dash gone
    assert "--" not in out      # double hyphen collapsed
    assert "-" in out           # replaced with single hyphen
    # original words survive
    for word in ("alpha", "beta", "gamma", "delta"):
        assert word in out


def test_render_letter_pdf_returns_pdf_bytes_with_umlauts():
    pdf = pytest.importorskip("app.services.pdf", reason="pdf service not yet available")
    sender = {
        "name": "Georg Damyanov",
        "address": "Musterstrasse 1, 1010 Wien",
        "phone": "+43 660 1234567",
        "email": "georg@example.com",
    }
    body = (
        "Sehr geehrte Damen und Herren,\n\n"
        "ich moechte mich fuer die Stelle bewerben. "
        "Ueber die Umlaute aeoeue und das scharfe szett gross."
        "äöüß\n\nMit freundlichen Gruessen"
    )
    out = pdf.render_letter_pdf(
        sender=sender,
        subject="Bewerbung als Backend Engineer",
        body=body,
        date_str="23. Juni 2026",
        language="de",
    )
    assert isinstance(out, (bytes, bytearray))
    assert bytes(out).startswith(b"%PDF")
    assert len(out) > 100


# ---------------------------------------------------------------------------
# 3. bundle module
# ---------------------------------------------------------------------------


def test_build_zip_roundtrips_skips_empty_and_dedupes():
    bundle = pytest.importorskip("app.services.bundle", reason="bundle service not yet available")
    files = [
        ("letter.pdf", b"%PDF-letter"),
        ("cv.pdf", b"%PDF-cv-content"),
        ("empty.txt", b""),            # should be skipped
        ("cv.pdf", b"%PDF-duplicate"), # duplicate arcname -> de-duped
    ]
    blob = bundle.build_zip(files)
    assert isinstance(blob, (bytes, bytearray))

    with zipfile.ZipFile(io.BytesIO(bytes(blob))) as zf:
        names = zf.namelist()
        # empty entry skipped
        assert "empty.txt" not in names
        # original non-empty present
        assert "letter.pdf" in names
        assert zf.read("letter.pdf") == b"%PDF-letter"
        # de-dupe: "cv.pdf" must appear exactly once across the archive
        assert names.count("cv.pdf") == 1
        # no duplicate names overall
        assert len(names) == len(set(names))
        # the de-duped second entry (if kept under a different name) must be unique
        for n in names:
            assert zf.read(n)  # nothing empty made it in


# ---------------------------------------------------------------------------
# 4 & 5. generation module
# ---------------------------------------------------------------------------


def test_build_messages_includes_identity_language_and_no_ams():
    generation = pytest.importorskip("app.services.generation", reason="generation service not yet available")
    profile = make_profile()
    application = make_application(language="de")
    cvs = make_cvs()

    system, user = generation.build_messages(
        profile=profile,
        application=application,
        cvs=cvs,
        language="de",
        produce_letter=True,
        produce_email=True,
        extra="",
    )
    combined = (system or "") + "\n" + (user or "")

    assert profile.name in combined
    # CV extracted_text is the grounding source (employers block removed in Task 4).
    assert cvs[0].extracted_text in combined
    # target language mentioned somewhere
    assert ("de" in combined.lower()) or ("german" in combined.lower()) or ("deutsch" in combined.lower())
    # The user-facing prompt (job-specific content) must never reference AMS.
    # The system prompt may instruct the model NOT to mention AMS, so we only
    # forbid it appearing as genuine application content in the user prompt.
    assert "AMS" not in (user or "")


def _required_types():
    return {
        "motivation_letter": str,
        "email_subject": str,
        "email_body": str,
        "recommended_cv_label": str,
        "recommended_cv_reason": str,
        "extracted": dict,
    }


def test_generate_fills_all_keys_and_validates_cv_label():
    generation = pytest.importorskip("app.services.generation", reason="generation service not yet available")
    profile = make_profile()
    application = make_application(language="de")
    cvs = make_cvs()

    # AI returns a partial dict missing several keys, and a bogus cv label.
    ai = FakeAI(json_result={
        "motivation_letter": "Sehr geehrte Damen und Herren ...",
        "recommended_cv_label": "Nonexistent Variant",
    })

    result = generation.generate(
        ai,
        profile=profile,
        application=application,
        cvs=cvs,
        language="de",
        produce_letter=True,
        produce_email=True,
    )

    assert isinstance(result, dict)
    for key, typ in _required_types().items():
        assert key in result, f"missing key {key}"
        assert isinstance(result[key], typ), f"{key} should be {typ}, got {type(result[key])}"

    labels = {c.label for c in cvs}
    assert result["recommended_cv_label"] == "" or result["recommended_cv_label"] in labels
    schema = ai.calls[-1]["schema"]
    assert schema["type"] == "object"
    assert set(schema["required"]) == set(_required_types())
    assert schema["additionalProperties"] is False


def test_generate_raises_generation_error_when_ai_fails():
    generation = pytest.importorskip("app.services.generation", reason="generation service not yet available")
    assert hasattr(generation, "GenerationError")
    profile = make_profile()
    application = make_application(language="de")
    cvs = make_cvs()

    ai = FakeAI(raise_exc=RuntimeError("ai boom"))

    with pytest.raises(generation.GenerationError):
        generation.generate(
            ai,
            profile=profile,
            application=application,
            cvs=cvs,
            language="de",
            produce_letter=True,
            produce_email=True,
        )


# ---------------------------------------------------------------------------
# 6. intake module
# ---------------------------------------------------------------------------


def test_normalize_collapses_blank_lines_and_strips():
    intake = pytest.importorskip("app.services.intake", reason="intake service not yet available")
    raw = "  first line\n\n\n\n\nsecond line  "
    out = intake.normalize(raw)
    assert "\n\n\n" not in out          # 3+ blank lines collapsed to at most 2 newlines
    assert out == out.strip()           # leading/trailing whitespace stripped
    assert "first line" in out
    assert "second line" in out


def test_intake_paste_mode_strips():
    intake = pytest.importorskip("app.services.intake", reason="intake service not yet available")
    assert intake.intake(mode="paste", text="  hi  ") == "hi"


def test_intake_bogus_mode_raises():
    intake = pytest.importorskip("app.services.intake", reason="intake service not yet available")
    assert hasattr(intake, "IntakeError")
    with pytest.raises(intake.IntakeError):
        intake.intake(mode="bogus", text="whatever")


def test_model_shape_cv_text_and_dropped_profile_fields():
    from app.models import CVVariant, Profile

    assert hasattr(CVVariant, "extracted_text")
    for gone in ("headline", "skills", "summary", "employers"):
        assert not hasattr(Profile, gone), f"Profile.{gone} should be removed"


# ---------------------------------------------------------------------------
# 7. cv_text module
# ---------------------------------------------------------------------------


def _make_text_pdf(text: str) -> bytes:
    """Build a one-page PDF with a real text layer using ReportLab (already a dep)."""
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 800, text)
    c.showPage()
    c.save()
    return buf.getvalue()


class _FakeAI:
    def complete(self, prompt, *, system=None, files=None, timeout=None):
        return "AI TRANSCRIBED CV"

    def complete_json(self, prompt, *, system=None, files=None, timeout=None, schema=None):
        return {}


def test_extract_cv_text_reads_pdf_text_layer():
    from app.services.cv_text import extract_cv_text

    data = _make_text_pdf("Senior Engineer at Fezle since 2023")
    out = extract_cv_text(data, "cv.pdf", _FakeAI())
    assert "Senior Engineer at Fezle" in out


def test_extract_cv_text_falls_back_to_ai_when_no_text_layer():
    from app.services.cv_text import extract_cv_text

    # Not a real PDF -> pdfplumber raises IntakeError -> AI fallback.
    out = extract_cv_text(b"not-a-real-pdf", "cv.pdf", _FakeAI())
    assert out == "AI TRANSCRIBED CV"


def test_extract_cv_text_returns_empty_without_ai_fallback():
    from app.services.cv_text import extract_cv_text

    out = extract_cv_text(b"not-a-real-pdf", "cv.pdf", ai=None)
    assert out == ""


def test_ensure_cv_text_fills_and_persists():
    from types import SimpleNamespace
    from app.services.cv_text import ensure_cv_text

    cv = SimpleNamespace(r2_key="k", filename="cv.pdf", extracted_text="")
    commits = {"n": 0}
    db = SimpleNamespace(commit=lambda: commits.__setitem__("n", commits["n"] + 1))
    storage = SimpleNamespace(get=lambda key: b"not-a-real-pdf")

    out = ensure_cv_text(cv, db=db, storage=storage, ai=_FakeAI())
    assert out == "AI TRANSCRIBED CV"
    assert cv.extracted_text == "AI TRANSCRIBED CV"
    assert commits["n"] == 1


def test_ensure_cv_text_noop_when_already_present():
    from types import SimpleNamespace
    from app.services.cv_text import ensure_cv_text

    cv = SimpleNamespace(r2_key="k", filename="cv.pdf", extracted_text="already here")
    got = {"called": False}
    storage = SimpleNamespace(get=lambda key: got.__setitem__("called", True))
    db = SimpleNamespace(commit=lambda: None)

    out = ensure_cv_text(cv, db=db, storage=storage, ai=_FakeAI())
    assert out == "already here"
    assert got["called"] is False  # storage never touched


def test_extract_cv_text_oserror_in_ai_fallback_returns_empty(monkeypatch):
    """Fix 1 regression: a raw OSError from extract_image_text must not propagate."""
    import app.services.cv_text as cv_text_mod
    import app.services.intake as intake_mod

    monkeypatch.setattr(intake_mod, "extract_image_text", lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))

    # non-PDF bytes -> pdfplumber raises IntakeError -> AI fallback -> OSError should be swallowed
    out = cv_text_mod.extract_cv_text(b"not-a-real-pdf", "cv.pdf", object())
    assert out == ""


def test_build_messages_grounds_on_cv_text_not_employers():
    from types import SimpleNamespace
    from app.services.generation import build_messages

    profile = SimpleNamespace(
        name="Georgi", address="Wien", phone="+43", email="g@example.com",
        languages="German native", availability="Immediate", preferences="Remote ok",
    )
    application = SimpleNamespace(
        company="Acme", position="Engineer", job_text="We need Python.",
        location="", salary="", url="",
    )
    cvs = [
        SimpleNamespace(label="Fullstack", language="de", notes="hands-on",
                        extracted_text="Worked at Fezle building SaaS in Python."),
        SimpleNamespace(label="Leadership", language="de", notes="lead roles",
                        extracted_text="Led a team of five at Fezle."),
    ]
    system, user = build_messages(
        profile=profile, application=application, cvs=cvs, language="de",
        produce_letter=True, produce_email=True,
    )
    # CV text is present for grounding...
    assert "Worked at Fezle building SaaS in Python." in user
    assert "Led a team of five at Fezle." in user
    # ...and the recommendation labels are still there.
    assert "Fullstack" in user and "Leadership" in user
    # No employers section header anymore.
    assert "EMPLOYERS" not in user.upper()
    # Grounding rule references the CV as the source.
    assert "CV" in system
