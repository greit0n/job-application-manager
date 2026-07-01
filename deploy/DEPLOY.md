# Deploying to Hetzner (jobs.fezle.io)

Isolated per the global ops model: own user `jobsapp`, own port `127.0.0.1:8095`, own
DB on the host Postgres cluster (`:5433`), own R2 bucket, cloudflared-tunneled
`jobs.fezle.io`. **Fezle owns 80/443 - never touch its nginx/compose.**

Host: `168.119.58.28` (Ubuntu 24.04).

## 0. Pre-flight (always, before any change)
```bash
ssh hetzner
cat /root/SERVER_REGISTRY.md          # check port/DB/domain conflicts
cat /opt/ops-registry/AGENTS.md       # ops rules
ss -ltnp | grep -E ':(8095|5433)'     # confirm 8095 free; 5433 = host PG cluster
```
Append a dated entry to the host CHANGELOG after the deploy.

## 1. App user + code
```bash
sudo adduser --system --group --home /home/jobsapp jobsapp
sudo -iu jobsapp git clone <private-repo-url> /home/jobsapp/app   # this repo (private)
sudo -iu jobsapp python3 -m venv /home/jobsapp/app/backend/.venv
sudo -iu jobsapp /home/jobsapp/app/backend/.venv/bin/pip install -U pip
sudo -iu jobsapp /home/jobsapp/app/backend/.venv/bin/pip install -r /home/jobsapp/app/backend/requirements.txt
```
> The DejaVu fonts for PDF rendering are **vendored in the repo**
> (`backend/app/assets/fonts/`), so the server does **not** need matplotlib or any
> system font package.

## 2. Database (dedicated DB + role on the host cluster :5433)
```bash
sudo -u postgres psql -p 5433 -c "CREATE ROLE jobsapp LOGIN PASSWORD '<db-pass>';"
sudo -u postgres psql -p 5433 -c "CREATE DATABASE jobsapp OWNER jobsapp;"
cd /home/jobsapp/app/backend
sudo -iu jobsapp bash -lc 'cd ~/app/backend && .venv/bin/alembic upgrade head'
```

## 3. R2 bucket
Create bucket `jobsapp-documents` + a scoped S3 API token in georg's R2 account.
Note the endpoint (`https://<acct>.r2.cloudflarestorage.com`), key id, and secret.

## 4. Codex CLI (AI backend)
```bash
sudo -iu jobsapp bash -lc 'curl -fsSL https://chatgpt.com/codex/install.sh | sh'
sudo -iu jobsapp bash -lc 'export PATH="$HOME/.local/bin:$PATH"; codex login --device-auth'
sudo -iu jobsapp bash -lc 'export PATH="$HOME/.local/bin:$PATH"; codex doctor --summary'
printf 'Reply with exactly OK' | sudo -iu jobsapp bash -lc 'export PATH="$HOME/.local/bin:$PATH"; codex --ask-for-approval never exec --ephemeral --skip-git-repo-check --sandbox read-only --ignore-user-config --ignore-rules -'
```
This uses the `jobsapp` user's persisted Codex CLI ChatGPT/Codex subscription login in
`/home/jobsapp/.codex`. Do not configure an OpenAI Platform API key or Anthropic API key
for this app path.

## 5. backend/.env (server-only, never committed)
Create `/home/jobsapp/app/backend/.env` (owned by `jobsapp`, mode 600):
```ini
ENV=prod
DEBUG=false
SECRET_KEY=<python -c "import secrets;print(secrets.token_urlsafe(48))">
DATABASE_URL=postgresql+psycopg2://jobsapp:<db-pass>@localhost:5433/jobsapp
R2_ENDPOINT_URL=https://<acct>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<r2-key>
R2_SECRET_ACCESS_KEY=<r2-secret>
R2_BUCKET=jobsapp-documents
R2_REGION=auto
AI_BACKEND=codex_cli
AI_TIMEOUT=180
CODEX_BIN=/home/jobsapp/.local/bin/codex           # adjust to the real path (`which codex`)
CODEX_MODEL=                                       # empty = Codex CLI default
CODEX_HOME=/home/jobsapp/.codex
```
> Claude Code remains available only as a rollback backend if it is installed and
> authenticated separately (`AI_BACKEND=claude_code`). The active path is Codex CLI
> subscription auth; there is no Anthropic API fallback.

## 6. systemd
Install `deploy/jobsapp.service` (binds `127.0.0.1:8095`, `EnvironmentFile=.../backend/.env`):
```bash
sudo cp /home/jobsapp/app/deploy/jobsapp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jobsapp
curl -s http://127.0.0.1:8095/api/health     # {"status":"ok","env":"prod"}
```

## 7. Tunnel
Follow `deploy/cloudflared-ingress.md`: add the `jobs.fezle.io -> http://localhost:8095`
ingress rule, `cloudflared tunnel route dns <tunnel> jobs.fezle.io`, restart cloudflared.
Then `curl -s https://jobs.fezle.io/api/health`.

## 8. Seed the two accounts
Passwords are generated locally and handed to georg out-of-band - **never commit them**.
Run once per user (idempotent upsert by email):
```bash
cd /home/jobsapp/app/backend
sudo -iu jobsapp bash -lc 'cd ~/app/backend && .venv/bin/python -m app.seed \
  --email eliswerekio@gmail.com --password "<eliska-pass>" --name "Eliska Sindelarova"'
sudo -iu jobsapp bash -lc 'cd ~/app/backend && .venv/bin/python -m app.seed \
  --email damyanov95@gmail.com  --password "<georgi-pass>"  --name "Georgi Damyanov"'
```

## 9. First login (per user)
On first login the app **forces a profile completion modal** (name, address, phone,
email are required - they appear on the generated Motivationsschreiben sender block).
Each user then uploads their CV variant(s) under **CVs**, marking one as default and
adding "when to use" notes so the AI can recommend the right one per job.

## 10. Verify end-to-end
At `https://jobs.fezle.io`: log in -> complete profile -> upload a CV -> add an application
(paste a real posting) -> Generate (DE) -> confirm the letter/email look right and the CV
was recommended -> Download ZIP -> reopen the application and see all documents. Then
confirm per-user isolation (the other account sees none of it).

## 11. After the deploy
Update `/root/SERVER_REGISTRY.md` (port 8095, DB `jobsapp`, domain, `/home/jobsapp`) and
append a dated entry to the host CHANGELOG.
