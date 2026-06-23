# Job Application Manager

Private, AI-assisted job-application manager for two users, deployed at
**jobs.fezle.io**. Drop a job posting (paste / PDF / URL), let Claude draft a
tailored **Motivationsschreiben** and application email and pick the best CV
variant, track the application through its pipeline, and download a ready-to-send
ZIP (CV + letter). German and English.

> This repo is **private**. Real CVs, letters, postings, and profile data live in
> Postgres + Cloudflare R2 and are never committed. See `CLAUDE.md` for the rules.

## Stack

- **Backend:** Python / FastAPI (`backend/`) — auth, data, R2 storage, AI orchestration,
  ReportLab PDF generation, ZIP bundling.
- **Frontend:** dependency-free vanilla-JS SPA (`frontend/`), served statically by FastAPI.
- **Database:** PostgreSQL.
- **File storage:** Cloudflare R2 (S3-compatible).
- **AI:** Claude, via the Claude Code CLI on the server (subscription auth), behind a
  swappable `AIClient` interface (`AI_BACKEND=anthropic_api` switches to a pay-per-token key).
- **Hosting:** Hetzner, isolated and tunneled through Cloudflare (`jobs.fezle.io`).

## Local development

```bash
# 1. Postgres (exposed on :5433 to mirror prod)
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. Backend env
cp backend/.env.example backend/.env        # then edit

# 3. Python deps
python -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt   # Windows
# Linux/macOS: backend/.venv/bin/pip install -r backend/requirements.txt

# 4. Run
cd backend && .venv/Scripts/uvicorn app.main:app --reload        # http://localhost:8000
cd backend && .venv/Scripts/pytest                               # tests
```

The app serves the frontend at `/` and the JSON API under `/api`.

## Layout

```
backend/    FastAPI app, services (ai_client, intake, generation, pdf, storage, bundle), tests
frontend/   index.html SPA + assets
deploy/     docker-compose.dev.yml, jobsapp.service, cloudflared-ingress.md, DEPLOY.md
docs/       usage / workflow notes
```

## Deployment

See `deploy/DEPLOY.md`. Follows the host's multi-project isolation model (own user, port,
DB, R2 bucket; cloudflared-tunneled subdomain). Fezle owns 80/443 on the box — untouched.

## License

MIT. See `LICENSE`. (Code is generic; all personal data stays out of the repo.)
