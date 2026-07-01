"""Application configuration, loaded from environment / .env.

Secrets (DB URL, R2 keys, session secret, CLI auth state) come from the
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

    # AI backend: "codex_cli" (Codex CLI with ChatGPT/Codex login) | "claude_code" (rollback)
    ai_backend: str = "codex_cli"
    ai_timeout: int = 180  # seconds per generation/transcription
    codex_bin: str = "codex"  # path to the codex executable on the server
    codex_model: str = ""  # empty = CLI default
    codex_home: str = ""  # empty = CLI default ~/.codex; prod can set /home/jobsapp/.codex

    # Claude Code rollback settings. Not used unless AI_BACKEND=claude_code.
    claude_bin: str = "claude"  # path to the claude executable on the server
    claude_code_oauth_token: str = ""  # from `claude setup-token` (env on the server)
    claude_model: str = ""  # empty = CLI default; e.g. "claude-opus-4-8" or "opus"
    claude_effort: str = ""  # CLI --effort: low|medium|high|xhigh|max ("" = default)

    @property
    def ai_model_label(self) -> str:
        """Compact audit label for the active backend/model pair."""
        backend = (self.ai_backend or "").strip()
        if backend == "codex_cli":
            model = self.codex_model.strip()
        elif backend == "claude_code":
            model = self.claude_model.strip()
        else:
            model = ""
        return f"{backend}:{model}" if model else backend

    # Frontend static dir (served by FastAPI). Resolved relative to repo root.
    frontend_dir: str = "../frontend"


@lru_cache
def get_settings() -> Settings:
    return Settings()
