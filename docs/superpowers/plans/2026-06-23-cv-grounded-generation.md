# CV-Grounded Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the uploaded CV the source of truth for candidate experience — generation reads CV text directly, and the duplicated content profile fields (headline/skills/summary/employers) are removed.

**Architecture:** On upload (and lazily before generation) each CV's text is extracted (pdfplumber → AI-transcription fallback) and cached on `CVVariant.extracted_text`. The generation prompt drops the employers block and the headline/skills/summary profile lines, and instead feeds the text of *all* CV variants as the single experience/grounding source — which also drives the "recommend a variant" output. A guard refuses letter/email generation when no CV has usable text.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2 / Alembic / Pydantic v2 / pdfplumber / ReportLab; vanilla-JS SPA (no build); pytest.

## Global Constraints

Copied verbatim from the project rules — every task implicitly includes these:

- **AI only behind `AIClient`.** Never call an AI SDK/API from a router; go through the injected `ai` object (`complete` / `complete_json`).
- **Never invent** experience, employers, job titles, education, certifications, credentials, skills or compensation. Frame gaps honestly. **Never mention AMS** / job centre / that the candidate was told to apply.
- **PDF/letter formatting unchanged:** A4, DejaVu Sans, real umlauts (ä ö ü ß — never transliterate), `TA_LEFT` (never justify), **single ASCII hyphen only** (no em/en dashes, no `--`).
- **Frontend stays dependency-free vanilla JS**, served as static files. No build step.
- **Per-user scoping** preserved on every endpoint (CVs/profiles/apps are already `user_id`-scoped).
- **No third-party analytics/telemetry.**
- **Keep `CLAUDE.md` and `AGENTS.md` equivalent** — change one, change the other.
- Run tests from `backend/` with `.venv/Scripts/pytest` (Windows). Tests build the schema from the ORM models via `Base.metadata.create_all` (SQLite in-memory), **not** via Alembic — so model changes take effect in tests automatically; the Alembic migration is for the deployed Postgres only.

---

### Task 1: Data model + Alembic migration

**Files:**
- Modify: `backend/app/models.py` (Profile class ~lines 50-72; CVVariant class ~lines 75-91)
- Create: `backend/alembic/versions/e2f1a7c9b3d4_cv_text_drop_profile_content.py`
- Test: `backend/tests/test_services.py` (append a model-shape test)

**Interfaces:**
- Produces: `CVVariant.extracted_text: str` (ORM column, default `""`). `Profile` no longer has `headline`, `skills`, `summary`, `employers` attributes.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_services.py`:

```python
def test_model_shape_cv_text_and_dropped_profile_fields():
    from app.models import CVVariant, Profile

    assert hasattr(CVVariant, "extracted_text")
    for gone in ("headline", "skills", "summary", "employers"):
        assert not hasattr(Profile, gone), f"Profile.{gone} should be removed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_services.py::test_model_shape_cv_text_and_dropped_profile_fields -v`
Expected: FAIL (`Profile.headline` still present / `CVVariant.extracted_text` missing).

- [ ] **Step 3: Edit the models**

In `backend/app/models.py`, in `class Profile`, **delete** these four lines:

```python
    headline: Mapped[str] = mapped_column(String(255), default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    # [{name, role, start, end, highlights:[...]}, ...] used to ground letters.
    employers: Mapped[list] = mapped_column(JSON, default=list)
```

(Keep `languages`, `availability`, `preferences`.) `JSON` may now be an unused import — leave it; it is harmless and re-added below is not needed. Actually remove `JSON` from the import list at the top **only if** no other model uses it. `Application.extracted` and `Generation` use `JSON`? Check: `Application.extracted: Mapped[dict] = mapped_column(JSON, ...)` — yes, `JSON` is still used. **Leave the `JSON` import.**

In `class CVVariant`, after the `notes` line add:

```python
    extracted_text: Mapped[str] = mapped_column(Text, default="")  # CV text for grounding generation
```

- [ ] **Step 4: Create the Alembic migration**

Create `backend/alembic/versions/e2f1a7c9b3d4_cv_text_drop_profile_content.py`:

```python
"""Add cv_variants.extracted_text; drop profile content fields.

The uploaded CV is now the source of truth for experience, so the duplicated
headline/skills/summary/employers profile fields are removed. Dropping
`employers` permanently discards its data (intended).

Revision ID: e2f1a7c9b3d4
Revises: fdfc27938220
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f1a7c9b3d4"
down_revision = "fdfc27938220"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cv_variants",
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_column("profiles", "headline")
    op.drop_column("profiles", "skills")
    op.drop_column("profiles", "summary")
    op.drop_column("profiles", "employers")


def downgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("employers", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "profiles",
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "profiles",
        sa.Column("skills", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "profiles",
        sa.Column("headline", sa.String(length=255), nullable=False, server_default=""),
    )
    op.drop_column("cv_variants", "extracted_text")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_services.py::test_model_shape_cv_text_and_dropped_profile_fields -v`
Expected: PASS.

- [ ] **Step 6: Verify the migration on the dev Postgres (best-effort)**

If the dev DB is up (`docker compose -f deploy/docker-compose.dev.yml up -d`):
Run: `cd backend && .venv/Scripts/alembic upgrade head && .venv/Scripts/alembic downgrade -1 && .venv/Scripts/alembic upgrade head`
Expected: all three succeed (no errors). If the dev DB is not available, skip and note it — the migration is exercised at deploy time.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/e2f1a7c9b3d4_cv_text_drop_profile_content.py backend/tests/test_services.py
git commit -m "feat: add CVVariant.extracted_text, drop profile content fields"
```

---

### Task 2: Pydantic schemas

**Files:**
- Modify: `backend/app/schemas.py` (`ProfileIn` ~lines 26-37)
- Test: `backend/tests/test_api.py` (add a profile round-trip test)

**Interfaces:**
- Consumes: nothing from earlier tasks at the type level.
- Produces: `ProfileIn` / `ProfileOut` carry only `name, address, phone, email, languages, availability, preferences` (+ `ProfileOut`'s `id`, `updated_at`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py` (it already has a `client` fixture + `login` helper via conftest; check the file header for the import — use the same pattern the file already uses):

```python
def test_profile_drops_content_fields(client):
    from .conftest import login
    login(client)
    resp = client.put(
        "/api/profile",
        json={
            "name": "Georgi", "address": "Wien", "phone": "+43", "email": "g@example.com",
            "languages": "German native", "availability": "Immediate",
            "preferences": "Remote ok",
            # legacy keys a stale client might still send — must be ignored, not stored:
            "headline": "X", "skills": "Y", "summary": "Z", "employers": [{"name": "Old"}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Georgi"
    for gone in ("headline", "skills", "summary", "employers"):
        assert gone not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py::test_profile_drops_content_fields -v`
Expected: FAIL (`headline` still present in the response body).

- [ ] **Step 3: Edit the schema**

In `backend/app/schemas.py` replace the `ProfileIn` class body with:

```python
class ProfileIn(BaseModel):
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    languages: str = ""
    availability: str = ""
    preferences: str = ""
```

Leave `ProfileOut(ProfileIn, ORMModel)` and its `id` / `updated_at` as-is. The `Field` import may become unused — check the rest of the file: `ApplicationOut` uses `Field(default_factory=list)`, so **leave the `Field` import**.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py::test_profile_drops_content_fields -v`
Expected: PASS. (Extra keys like `headline` are ignored by Pydantic v2 default and never reach the ORM.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_api.py
git commit -m "feat: drop content fields from Profile schemas"
```

---

### Task 3: CV text extraction service

**Files:**
- Create: `backend/app/services/cv_text.py`
- Test: `backend/tests/test_services.py`

**Interfaces:**
- Consumes: `intake.extract_pdf_text(data) -> str` (raises `IntakeError`), `intake.extract_image_text(data, filename, ai, *, timeout) -> str`, `CVVariant.extracted_text`, the `Storage` interface (`get(key) -> bytes`).
- Produces:
  - `extract_cv_text(data: bytes, filename: str, ai, *, timeout: int | None = None) -> str` — pdfplumber first; on `IntakeError` fall back to AI transcription; returns `""` on total failure (never raises).
  - `ensure_cv_text(cv, *, db, storage, ai, timeout: int | None = None) -> str` — if `cv.extracted_text` is empty, fetch bytes from `storage`, call `extract_cv_text`, persist + commit. Returns the (possibly still empty) text. Best-effort: storage/extraction failure leaves it empty and does not raise.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_services.py`:

```python
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

    def complete_json(self, prompt, *, system=None, files=None, timeout=None):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/test_services.py -k cv_text -v`
Expected: FAIL (`No module named app.services.cv_text`).

- [ ] **Step 3: Create the service**

Create `backend/app/services/cv_text.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/test_services.py -k cv_text -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cv_text.py backend/tests/test_services.py
git commit -m "feat: cv_text service (pdfplumber + AI-fallback extraction)"
```

---

### Task 4: Generation prompt rewrite

**Files:**
- Modify: `backend/app/services/generation.py` (`_format_cvs` ~91-108; `_profile_block` ~111-124; `_format_employers` ~59-88; `_system_prompt` ~127-199; `build_messages` ~202-310)
- Test: `backend/tests/test_services.py`

**Interfaces:**
- Consumes: `CVVariant.extracted_text`; reduced `Profile` (no headline/skills/summary/employers).
- Produces: `build_messages(...)` user prompt contains every CV variant's `extracted_text` and no employers block; `_format_cvs(cvs) -> tuple[str, list[str]]` still returns `(text, labels)` with `labels` used for recommendation validation.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_services.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_services.py::test_build_messages_grounds_on_cv_text_not_employers -v`
Expected: FAIL (either `extracted_text` not rendered, or the `EMPLOYERS` header still present).

- [ ] **Step 3: Rewrite `_format_cvs`**

In `backend/app/services/generation.py` replace `_format_cvs` with:

```python
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
```

- [ ] **Step 4: Reduce `_profile_block` and delete `_format_employers`**

Replace `_profile_block` field list (drop Headline/Skills/Summary):

```python
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
```

**Delete the entire `_format_employers` function** (lines ~59-88).

- [ ] **Step 5: Update `build_messages`**

In `build_messages`, remove the employers wiring and re-point the CV block. Delete this line:

```python
    employers_block = _format_employers(getattr(profile, "employers", None))
```

In the user-prompt list, delete these two list entries:

```python
            "=== CANDIDATE EMPLOYERS (real work history - your only source for experience) ===",
            employers_block,
            "",
```

and change the CV section header line from:

```python
            "=== AVAILABLE CV VARIANTS (recommend the best-fitting label) ===",
```

to:

```python
            "=== CANDIDATE CVs (full text - your ONLY source for real experience; also recommend the best-fitting label) ===",
```

- [ ] **Step 6: Update the grounding rule in `_system_prompt`**

In `_system_prompt`, change the first GROUNDING RULES bullet from referencing "the supplied candidate profile and employers list" to the CV. Replace the bullet text:

```python
            "- Base EVERYTHING only on the supplied candidate profile and employers list. "
            "NEVER invent experience, employers, job titles, education, certifications, "
            "credentials, skills or compensation. If the candidate lacks something the job "
            "wants, frame the gap honestly (e.g. conceptually familiar, would formally "
            "build it up) instead of fabricating.",
```

with:

```python
            "- The candidate's CV(s), reproduced in full below, are your ONLY source for "
            "experience, employers, job titles, education, certifications, credentials and "
            "skills. NEVER invent anything beyond them. If the candidate lacks something the "
            "job wants, frame the gap honestly (e.g. conceptually familiar, would formally "
            "build it up) instead of fabricating.",
```

Also in the LETTER CRAFT step 2, change "use the employers list" to "use the CV(s)":

```python
            "2. Develop with concrete experience at the candidate's actual employers (use "
            "the employers list), tying achievements to what the job needs.",
```

becomes:

```python
            "2. Develop with concrete experience at the candidate's actual employers (drawn "
            "from the CV text), tying achievements to what the job needs.",
```

- [ ] **Step 7: Run the targeted test + full service suite**

Run: `cd backend && .venv/Scripts/pytest tests/test_services.py -v`
Expected: PASS (new `build_messages` test + existing service tests). If any existing service test referenced employers, update it to use `extracted_text` instead.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/generation.py backend/tests/test_services.py
git commit -m "feat: ground generation prompt on CV text, drop employers block"
```

---

### Task 5: Extract CV text on upload

**Files:**
- Modify: `backend/app/routers/cvs.py` (`upload_cv` ~37-70)
- Test: covered behaviorally by Task 6's end-to-end guard test (an uploaded CV must yield usable text); no isolated router test needed since `CVOut` does not expose `extracted_text`.

**Interfaces:**
- Consumes: `cv_text.ensure_cv_text(cv, *, db, storage, ai, timeout)`, `get_ai_client()`, `run_in_threadpool`.

- [ ] **Step 1: Add imports**

In `backend/app/routers/cvs.py` add near the existing imports:

```python
from fastapi.concurrency import run_in_threadpool

from ..config import get_settings
from ..services.ai_client import get_ai_client
from ..services.cv_text import ensure_cv_text
```

- [ ] **Step 2: Extract after the CV row is committed**

In `upload_cv`, after `db.refresh(cv)` and before `return cv`, insert:

```python
    # Cache the CV's text now so generation can ground on it. Best-effort: a
    # failure here just leaves extracted_text empty; it is retried lazily at
    # generation time. Run off the event loop (blocking R2 + pdfplumber + CLI).
    try:
        await run_in_threadpool(
            ensure_cv_text,
            cv,
            db=db,
            storage=get_storage(),
            ai=get_ai_client(),
            timeout=get_settings().claude_timeout,
        )
    except Exception:
        pass
    db.refresh(cv)
```

- [ ] **Step 3: Run the CV + generation suites**

Run: `cd backend && .venv/Scripts/pytest tests/test_generation_flow.py tests/test_api.py -v`
Expected: PASS (the fake-AI flow uploads a non-text "PDF" → fallback → `extracted_text` set). Fix any fallout before committing.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/cvs.py
git commit -m "feat: extract CV text on upload"
```

---

### Task 6: Generation guard + lazy backfill

**Files:**
- Modify: `backend/app/routers/generation.py` (`generate_documents` ~164-246)
- Modify: `backend/tests/test_generation_flow.py` (`_fill_profile`, add guard test)
- Test: `backend/tests/test_generation_flow.py`

**Interfaces:**
- Consumes: `cv_text.ensure_cv_text`, the already-imported `get_storage`, `get_settings`, `cvs` list.

- [ ] **Step 1: Write/adjust the tests**

In `backend/tests/test_generation_flow.py`:

(a) Simplify `_fill_profile` to drop `employers` (no longer a field):

```python
def _fill_profile(client):
    resp = client.put(
        "/api/profile",
        json={
            "name": "Georgi Damyanov",
            "address": "Hafinger Weg 8/3, 3100 St. Pölten",
            "phone": "+43 681 20858721",
            "email": "georgi@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
```

(b) Add a guard test (profile complete, but no CV uploaded):

```python
def test_generate_requires_a_cv_with_text(client, ai_client):
    login(client)
    _fill_profile(client)  # name + address present, but NO CV uploaded
    app_id = client.post(
        "/api/applications/intake",
        data={"mode": "paste", "text": "Senior Engineer at Acme", "language": "de"},
    ).json()["id"]
    resp = client.post(
        f"/api/applications/{app_id}/generate",
        json={"language": "de", "produce_letter": True, "produce_email": False},
    )
    assert resp.status_code == 422
    assert "cv" in resp.json()["detail"].lower()
```

- [ ] **Step 2: Run to verify the new test fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_generation_flow.py::test_generate_requires_a_cv_with_text -v`
Expected: FAIL (currently generation proceeds and returns 200/502 instead of 422).

- [ ] **Step 3: Add the imports**

In `backend/app/routers/generation.py` add to the services imports block:

```python
from ..services.cv_text import ensure_cv_text
```

(`get_storage`, `get_settings` are already imported.)

- [ ] **Step 4: Lazy backfill + guard**

In `generate_documents`, just after `cvs = list(db.scalars(...))` and the `language = ...` line, and after the existing name/address guard, insert:

```python
    # Lazily backfill CV text for any variant uploaded before extraction existed
    # (self-healing) so grounding has the real experience to draw on.
    storage = get_storage()
    for cv in cvs:
        if not (cv.extracted_text or "").strip():
            ensure_cv_text(
                cv,
                db=db,
                storage=storage,
                ai=ai,
                timeout=get_settings().claude_timeout,
            )

    # Generation grounds entirely on CV text now - refuse if there is none.
    if (payload.produce_letter or payload.produce_email) and not any(
        (cv.extracted_text or "").strip() for cv in cvs
    ):
        raise HTTPException(
            status_code=422,
            detail="Upload a CV with readable text before generating documents.",
        )
```

Note: place this **after** the existing `if payload.produce_letter and not (profile.name... )` guard so the "complete your profile" message still wins for the no-profile case (keeps `test_generate_requires_profile_for_letter` green). The later code already defines a local `storage = get_storage()` (~265) — remove that now-redundant re-assignment, or rename; simplest: delete the later `storage = get_storage()` line since `storage` is now defined above.

- [ ] **Step 5: Run the full generation suite**

Run: `cd backend && .venv/Scripts/pytest tests/test_generation_flow.py -v`
Expected: PASS (full flow, scoping, empty-paste, requires-profile, requires-CV).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/generation.py backend/tests/test_generation_flow.py
git commit -m "feat: lazy CV-text backfill + require CV text to generate"
```

---

### Task 7: Frontend — remove dropped fields & employers UI

**Files:**
- Modify: `frontend/index.html`

**Interfaces:** none (vanilla JS).

- [ ] **Step 1: Remove the dropped form inputs**

In `frontend/index.html`:

- Delete the Headline field block (~958-961: the `<div class="field">` containing `profileHeadline`).
- Delete the Skills field block (~982-985: `<div class="field full">` containing `profileSkills`).
- Delete the Summary field block (~986-989: `<div class="field full">` containing `profileSummary`).
- Delete the entire Employers section block (~996-1005: the `<div style="margin-top:24px;">` … through its closing `</div>` that holds the `Employers` panel-title, `addEmployer` button and `employerList`).

- [ ] **Step 2: Add the CV hint**

Change the panel note (~949) from:

```html
              <p class="panel-note">Used to generate your cover letters and application emails.</p>
```

to:

```html
              <p class="panel-note">Used to generate your cover letters and application emails. Your experience is read from your uploaded CVs.</p>
```

- [ ] **Step 3: Update the onboarding notice**

Change line ~1109 from:

```html
      <div class="notice warn" style="margin-top:16px;">You can fill in the rest of your profile (skills, employers, summary) later under Profile.</div>
```

to:

```html
      <div class="notice warn" style="margin-top:16px;">You can fill in the rest of your profile and upload your CVs later - your experience is read from the CVs you upload.</div>
```

- [ ] **Step 4: Remove the employers JS**

- Delete the CSS block introduced by `/* employers editor */` (~581 and the `.emp-*` rules that follow it, up to the next unrelated comment/selector).
- Delete `let employers = []; // working copy for the profile editor` (~1157).
- Delete the `employerList: document.getElementById("employerList"),` ref (~1189).
- In `loadProfile` (~1387-1390) delete the `employers = Array.isArray(...)` line.
- In `renderProfileForm` (~1707-1720) delete `setValue("profileHeadline", ...)`, `setValue("profileSkills", ...)`, `setValue("profileSummary", ...)`, and the `renderEmployers();` call.
- Delete the whole `renderEmployers()` function (~1722-1757) and the whole `syncEmployersFromDom()` function (~1759-1770).
- In `handleProfileSubmit` (~1773-1803): delete the `syncEmployersFromDom();` line; in the PUT `json` object delete the `headline`, `skills`, `summary`, and `employers` keys; delete the post-save `employers = Array.isArray(...)` line.
- In `currentProfilePayload` (~1441-1457) delete the `headline`, `skills`, `summary`, `employers` keys.
- In `saveProfilePayload` (~1458-1462) delete the `employers = Array.isArray(...)` line.
- Delete the two event listeners for `refs.addEmployer` and `refs.employerList` (~2240-2252).

- [ ] **Step 5: Manual verification**

Start the app (`cd backend && .venv/Scripts/uvicorn app.main:app --reload`), open `http://localhost:8000`, log in, open **Profile**. Confirm: no Headline/Skills/Summary fields, no Employers section, the page has no console errors, and **Save profile** persists name/address/phone/email/languages/availability/preferences. Grep to confirm no stale references remain:

Run: `grep -nE "employer|profileHeadline|profileSkills|profileSummary|renderEmployers|syncEmployersFromDom" frontend/index.html`
Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat: remove dropped profile fields and employers UI"
```

---

### Task 8: Docs — keep CLAUDE.md ≡ AGENTS.md

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md` (the "Document generation" section)

- [ ] **Step 1: Update the grounding wording**

In **both** `CLAUDE.md` and `AGENTS.md`, in the "Document generation — match the Bewerbungen output" section, update the grounding bullets so they say experience is grounded in the uploaded CV text (the candidate's CV is the source of truth for experience/employers), while still: never invent, frame gaps honestly, never mention AMS. Keep the two files byte-for-byte equivalent below the header note.

- [ ] **Step 2: Verify equivalence**

Run: `diff <(sed '1,3d' CLAUDE.md) <(sed '1,3d' AGENTS.md)` (or a manual side-by-side) and confirm the generation section matches.

- [ ] **Step 3: Run the whole suite once more**

Run: `cd backend && .venv/Scripts/pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "docs: CV is the experience source for generation"
```

---

## Self-Review

**Spec coverage:**
- Profile fields kept/removed → Task 1 (model), Task 2 (schema), Task 7 (UI). ✓
- `CVVariant.extracted_text` + migration → Task 1. ✓
- Extraction helper (pdfplumber → AI fallback) → Task 3. ✓
- Extract on upload → Task 5. ✓
- Lazy backfill before generation → Task 6. ✓
- Prompt rewrite (reduced profile, all-CV-text block, system rule) → Task 4. ✓
- Generation guard (≥1 CV with text) → Task 6. ✓
- Frontend removal + hint → Task 7. ✓
- Tests across all areas → folded into each task. ✓
- Employers data dropped permanently → Task 1 migration. ✓
- Docs equivalence → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `extracted_text` used identically in model (Task 1), service (Task 3), prompt (Task 4), upload (Task 5), guard (Task 6). `ensure_cv_text(cv, *, db, storage, ai, timeout)` and `extract_cv_text(data, filename, ai, *, timeout)` signatures match across Tasks 3/5/6. `_format_cvs` keeps its `(text, labels)` return used by `generate()`'s recommendation validation. ✓
