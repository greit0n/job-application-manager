"""Application configuration, loaded from environment / .env.

Secrets (DB URL, R2 keys, session secret, Claude token) come from the
environment and are NEVER committed. See backend/.env.example.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Runtime
    env: str = "dev"  # dev | prod
    debug: bool = True

    # Session signing (Starlette SessionMiddleware). Generate a random value in prod.
    secret_key: str = "dev-insecure-change-me"
    session_cookie: str = "jobsapp_session"
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days

    # Database
    database_url: str = "postgresql+psycopg2://jobsapp:jobsapp@localhost:5433/jobsapp"

    # Cloudflare R2 (S3-compatible). endpoint like https://<acct>.r2.cloudflarestorage.com
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "jobsapp-documents"
    r2_region: str = "auto"
    # Local dev can point at MinIO; presigned-URL TTL in seconds
    presign_ttl: int = 600

    # AI backend: "claude_code" (CLI subprocess, subscription) | "anthropic_api" (key)
    ai_backend: str = "claude_code"
    claude_bin: str = "claude"  # path to the claude executable on the server
    claude_code_oauth_token: str = ""  # from `claude setup-token` (env on the server)
    claude_model: str = ""  # empty = CLI default; e.g. "claude-opus-4-8" or "opus"
    claude_effort: str = ""  # CLI --effort: low|medium|high|xhigh|max ("" = default)
    claude_timeout: int = 180  # seconds per generation
    anthropic_api_key: str = ""  # only for the anthropic_api backend

    # Gmail OAuth / drafts. Scope stays compose-only: create/update drafts, no send.
    gmail_oauth_client_id: str = ""
    gmail_oauth_client_secret: str = ""
    gmail_oauth_redirect_uri: str = ""  # e.g. https://jobs.fezle.io/api/gmail/callback
    gmail_oauth_scopes: str = "https://www.googleapis.com/auth/gmail.compose"
    gmail_token_encryption_key: str = ""  # stable secret; falls back to SECRET_KEY in dev
    gmail_oauth_success_url: str = "/?gmail=connected"

    # Frontend static dir (served by FastAPI). Resolved relative to repo root.
    frontend_dir: str = "../frontend"


@lru_cache
def get_settings() -> Settings:
    return Settings()
