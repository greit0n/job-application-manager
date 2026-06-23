# CV-grounded generation — design

**Date:** 2026-06-23
**Status:** Approved (design); pending implementation plan

## Problem

The candidate profile re-asks for experience the user already has in their CV.
Generation currently grounds **entirely** on typed profile fields
(`_profile_block` + `profile.employers`); the uploaded CV PDFs are never read by
the model — only their `label`/`notes` reach the prompt, purely so the AI can
recommend which variant to attach. The user types their experience twice (once
into the CV, once into the profile), and the richest source of truth (the CV) is
invisible to generation.

## Decision

Make the uploaded CV the source of truth for experience. Generation reads CV
text directly. The duplicated **content** profile fields are removed.

Decisions locked during brainstorming:

- **Approach:** drop the content fields and ground on CV text (not auto-fill).
- **Grounding scope:** *all* CV variants combined — the model sees every
  variant's text, grounds on the union of real experience, and picks the
  best-fit variant to recommend from the same view.
- **Scanned/image-only CVs:** AI-transcribe fallback so every CV ends with
  usable grounding text.
- **Employers data:** dropped permanently (clean schema), not kept as dead
  columns.
- **Backfill of existing CVs:** lazy "extract-if-missing at generation", not a
  one-time script — self-healing, only a couple of CVs exist.

## Scope

### 1. Profile fields kept vs removed

Keep (structured, not reliably in a CV, or needed verbatim for the PDF sender
block): **name, address, phone, email, languages, availability, preferences.**

Remove: **headline, skills, summary, employers.**

The four removed columns are dropped from the `profiles` table via Alembic
migration. This **permanently discards any existing `employers` JSON data** —
acceptable because the CV now supersedes it.

### 2. `CVVariant.extracted_text`

Add `extracted_text: Mapped[str] = mapped_column(Text, default="")` to
`cv_variants`. This is the experience source fed to the prompt.

### 3. Extraction helper

`ensure_cv_text(cv, *, ai, storage, db)` — populates `cv.extracted_text` when
empty:

1. Fetch CV bytes from R2 (`storage.get(cv.r2_key)`).
2. Try `intake.extract_pdf_text(bytes)` (pdfplumber text layer).
3. On `IntakeError` (no text layer), fall back to
   `intake.extract_image_text(bytes, filename, ai, ...)` — the existing
   AI-transcription path.
4. Persist the result to `cv.extracted_text` and commit.

Called:
- **On upload** in `routers/cvs.py::upload_cv` (best-effort; an extraction
  failure must not block the upload — the CV file still stores, text stays
  empty and is retried lazily later).
- **Lazily before generation** in `routers/generation.py::generate_documents`
  for every CV whose `extracted_text` is empty. This self-heals already-uploaded
  CVs.

Extraction does blocking I/O (R2 + pdfplumber + possibly a Claude subprocess) —
run it off the event loop the same way intake already does
(`run_in_threadpool`) where it sits on the request path.

### 4. Generation prompt rewrite (`services/generation.py`)

- `_profile_block`: reduce to the kept fields only (name, address, phone, email,
  languages, availability, preferences). Drop headline/skills/summary.
- Delete `_format_employers` and the `=== CANDIDATE EMPLOYERS ===` block from
  `build_messages`.
- `_format_cvs`: extend so each variant emits `label` + `language` + `notes` +
  the full `extracted_text`. This single block (renamed to e.g.
  `=== CANDIDATE CVs (your only source for real experience; also recommend the
  best-fitting label) ===`) serves **both** grounding and the recommendation.
  Keep returning the `labels` list for recommendation validation.
- System prompt grounding rule rewritten: the candidate's CV(s) are the ONLY
  source for experience, employers, job titles, education, certifications,
  credentials and skills — never invent beyond them; frame gaps honestly; never
  mention AMS. (Keep all existing formatting / dash / umlaut / language rules.)

### 5. Generation guard (`routers/generation.py`)

Existing guard (letter requires `profile.name` + `profile.address`) stays. Add,
after the lazy extraction pass: if **no** CV has non-empty `extracted_text`,
return `422` — *"Upload a CV with readable text before generating."* This
applies whenever a letter or email is requested (both make experience claims).

### 6. Frontend (`frontend/index.html`)

- Remove the Headline, Skills, and Summary inputs and the entire **Employers**
  section (heading, "Add employer" button, the employer rows + their JS
  state/handlers) from the Profile view.
- Add a one-line hint under the profile intro: *"Your experience is read from
  your uploaded CVs."*
- Remove the dropped fields from the profile read/save payload handling.

### 7. Schemas (`backend/app/schemas.py`)

- `ProfileOut` / `ProfileUpdate` (and any profile base): remove `headline`,
  `skills`, `summary`, `employers`.

## Architecture / data flow

```
Upload CV ──▶ store bytes in R2 ──▶ ensure_cv_text() ──▶ cv.extracted_text
                                       (pdfplumber → AI fallback)

Generate ──▶ for each CV: ensure_cv_text() if empty (lazy backfill)
         ──▶ guard: ≥1 CV with text, else 422
         ──▶ build_messages(): reduced profile block + ALL CV texts block
         ──▶ AI ──▶ letter/email + recommended_cv_label (from the same CV view)
```

The AI stays behind `AIClient`; PDF output and the Bewerbungen rules are
unchanged. Per-user scoping is unchanged (CVs are already user-scoped).

## Error handling

- Upload-time extraction failure: swallow, leave `extracted_text=""`, retry
  lazily at generation. The upload itself must succeed.
- Generation-time extraction failure for a given CV: leave that CV's text empty
  and continue; the guard catches the "no usable CV text at all" case.
- No CV with text → `422` with an actionable message (above).

## Testing

- `build_messages` includes each CV's `extracted_text`; excludes the removed
  profile fields and the employers block.
- `_format_cvs` still returns the labels list and renders text + notes.
- Generation guard returns 422 when no CV has `extracted_text`.
- `ensure_cv_text`: text-layer PDF stores pdfplumber output; scanned/no-text PDF
  triggers the AI-transcription fallback (fake AI) and stores that.
- Lazy backfill: a CV with empty `extracted_text` gets filled during
  `generate_documents`.
- Schema round-trip: profile create/update/read no longer carries the removed
  fields.
- Alembic migration upgrades and downgrades cleanly (downgrade re-adds the
  dropped columns as empty/default; `extracted_text` dropped on downgrade).

## Out of scope

- Auto-filling structured fields from the CV (explicitly rejected approach).
- Editing/parsing CV structure into typed sub-fields.
- Re-extracting on CV file replacement beyond the empty-text lazy path.
