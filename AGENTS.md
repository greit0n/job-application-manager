# Job Application Manager — Agent Instructions

> Kept equivalent to `CLAUDE.md` (which adds a Claude-Code header line). Change one, change the other.

## What this is

A **private, deployed, multi-user** AI job-application manager for georg and his
girlfriend. It is hosted on the Hetzner box (`168.119.58.28`) at **`jobs.fezle.io`**.
This repository is **private**; real CVs, letters, postings, and profile data live in
**Postgres + Cloudflare R2 and must never be committed**.

It replaces an earlier local-first static `index.html`. The product mirrors georg's proven
manual workflow in `C:\Users\georg\Documents\Bewerbungen` (German "Bewerbungen" = job
applications), now automated:

1. **Drop a job** — paste text, upload the posting PDF/screenshot, or paste a URL.
2. **AI generates** a Motivationsschreiben (motivation letter) + application email, in
   **DE or EN**, with checkboxes for what to produce, and **recommends which CV variant fits**.
3. It becomes a **tracked application** with a status.
4. **Download a ZIP** of CV + Motivationsschreiben (+ email).
5. Per application, **view all documents**: original posting, CV, letter, email, proofs.

## Architecture

```
frontend/index.html (vanilla-JS SPA, no build)  ──fetch JSON──▶  FastAPI (backend/app)
                                                                  ├── session-cookie auth (argon2), per-user scoping
                                                                  ├── Postgres (host cluster :5433, DB `jobsapp`)
                                                                  ├── R2 bucket `jobsapp-documents` (S3 API, boto3)
                                                                  ├── AIClient → CodexCliClient (`codex exec`)
                                                                  └── ReportLab PDFs → ZIP bundles
cloudflared tunnel: jobs.fezle.io → 127.0.0.1:8095   (edge SSL at Cloudflare)
```

- **Backend:** Python / FastAPI. `backend/app/` = `main.py`, `config.py` (pydantic-settings),
  `db.py` (SQLAlchemy 2), `models.py`, `schemas.py`, `auth.py`, `routers/`, `services/`.
- **AI is always behind `services/ai_client.py::AIClient`.** Default backend is
  `CodexCliClient` (shells out to `codex exec` using the `jobsapp` user's persisted
  ChatGPT/Codex subscription login under `CODEX_HOME`). `ClaudeCodeClient` remains an
  inactive rollback backend (`AI_BACKEND=claude_code`). **Never call an AI SDK/API
  directly from a router** — go through the interface.
- **Frontend** stays dependency-free vanilla JS, served as static files by FastAPI. It
  evolved from the old `index.html` (the `state`/`statuses`/`render()`/drawer/modal patterns
  remain) — but storage is now the API, not localStorage/IndexedDB.

## Commands

```bash
# Local dev (from repo root)
docker compose -f deploy/docker-compose.dev.yml up -d        # Postgres on :5433
cp backend/.env.example backend/.env                          # then fill in
codex login status                                             # if needed: codex login --device-auth
codex doctor --summary
"Reply with exactly OK" | codex --ask-for-approval never exec --ephemeral --skip-git-repo-check --sandbox read-only --ignore-user-config --ignore-rules -
python -m venv backend/.venv && backend/.venv/Scripts/pip install -r backend/requirements.txt   # Windows
#   (Linux/macOS: backend/.venv/bin/pip ...)
cd backend && .venv/Scripts/python -c "from app.config import get_settings; print(get_settings().ai_backend)"
cd backend && .venv/Scripts/python -c "from app.services.ai_client import get_ai_client; print(get_ai_client().complete('Reply with exactly OK'))"
cd backend && .venv/Scripts/uvicorn app.main:app --reload     # http://localhost:8000
cd backend && .venv/Scripts/pytest                            # tests

# DB migrations (Phase 1+)
cd backend && .venv/Scripts/alembic upgrade head
cd backend && .venv/Scripts/alembic revision --autogenerate -m "msg"
```

Local `backend/.env.example` defaults to `AI_BACKEND=codex_cli` and empty
`CODEX_HOME`, so local generation uses the logged-in local Codex CLI account.
Claude Code rollback settings stay commented unless intentionally re-enabled.
There is no frontend build step. Deployment runbook: `deploy/DEPLOY.md`.

## Document generation — match the Bewerbungen output

The Motivationsschreiben quality comes from the rules in
`C:\Users\georg\Documents\Bewerbungen\CLAUDE.md`. Replicate, do not water down:

- **Letters are AI-written per job, not templated.** Narrative arc: (1) interest +
  bridge from job requirements to real experience, (2) concrete experience at the
  candidate's real employers, (3) enthusiastic, company-specific close.
  **Experience, employers, education, and skills are drawn exclusively from the
  candidate's uploaded CV text** (`CVVariant.extracted_text`) — the CV is the sole
  source of truth; the profile supplies only name/address/contact/languages/availability.
- **Never invent** experience, employers, credentials, education, or compensation. Frame
  gaps honestly ("konzeptionell vertraut, würde formal ausbauen").
- **Never mention AMS** or that the candidate was told/required to apply — always frame as
  genuine interest.
- **PDF = ReportLab** (`services/pdf.py`): A4, **DejaVu Sans** registered via `pdfmetrics`
  for real Umlauts (ä ö ü ß — never transliterate), **`TA_LEFT` (never `TA_JUSTIFY`)**,
  **single hyphen only (no em/en dashes, no `--`)**, sender block from the user's profile.
- **Email** is shorter than the letter; subject `Bewerbung als <Position>`.
- **Bilingual:** generation language is per-application (`de`/`en`).
- Output filenames follow `Motivationsschreiben_<Company>.pdf`.

## Data & privacy rules

- The repo is private. **Never commit** real CVs, letters, postings, backups, screenshots,
  profile data, `.env`, R2 keys, CLI auth tokens, or DB dumps. `.gitignore` enforces this;
  verify with `git status` and a personal-data grep before any push.
- Profiles, applications, and document *metadata* live in Postgres; the *files*
  (CVs, postings, generated PDFs, ZIPs) live in R2. Every query is **scoped to the logged-in
  user** — georg and his girlfriend never see each other's data.
- Secrets come from the environment (`backend/.env` locally; systemd `EnvironmentFile` in
  prod). No secrets in code or git.

## App editing rules

- Keep the AI behind `AIClient`; keep PDF output faithful to the Bewerbungen rules above.
- Keep the frontend build-free vanilla JS unless the user explicitly changes direction.
- Preserve per-user data scoping on every new endpoint.
- Don't add third-party analytics/telemetry.
- Keep `CLAUDE.md` and `AGENTS.md` equivalent.

## Deployment (Hetzner)

Isolated per the global ops model (own user `jobsapp`, own port `8095`, own DB, own R2
bucket, cloudflared-tunneled `jobs.fezle.io`). **Fezle owns 80/443 — never touch its
nginx/compose.** Before any server change: read `/root/SERVER_REGISTRY.md` and
`/opt/ops-registry/AGENTS.md`, run read-only inventory, and append a dated entry to the
host CHANGELOG. Full steps: `deploy/DEPLOY.md`, `deploy/cloudflared-ingress.md`.

AI auth note: the deployed app drives Codex via `codex exec` on georg's ChatGPT/Codex
subscription, using the `jobsapp` user's persisted Codex CLI login. Do not add OpenAI
Platform API keys or Anthropic API keys for this app path. Claude Code is retained only as
an inactive rollback backend if it is ever re-authenticated separately.
