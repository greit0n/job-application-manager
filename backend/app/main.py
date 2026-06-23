"""FastAPI application entrypoint.

Serves the JSON API under /api and the static frontend SPA at /.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings

settings = get_settings()

# repo_root/frontend regardless of where uvicorn is launched from.
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = (REPO_ROOT / "frontend").resolve()


def create_app() -> FastAPI:
    app = FastAPI(title="Job Application Manager", debug=settings.debug)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie,
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.env == "prod",
    )

    @app.get("/api/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "env": settings.env})

    from .routers import applications, auth, cvs, documents, generation, profiles

    for module in (auth, profiles, cvs, applications, generation, documents):
        app.include_router(module.router, prefix="/api")

    # Static SPA last so /api/* wins. html=True serves index.html for "/".
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
