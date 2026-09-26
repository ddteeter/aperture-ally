"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import install_error_handlers, router
from .config import Settings, get_settings
from .services import PhotoCoachApp


def create_app(settings: Settings | None = None, coach: PhotoCoachApp | None = None, *, watch: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not app.state.coach.started:
            await app.state.coach.start(watch=watch)
        yield
        await app.state.coach.stop()

    app = FastAPI(title="Photo Coach", version="0.1.0", lifespan=lifespan)
    app.state.coach = coach or PhotoCoachApp(settings)
    # Loopback single-user service: reject foreign Host headers (DNS rebinding) and foreign origins.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["*"],
                       allow_headers=["*"], allow_credentials=False)
    app.include_router(router)
    install_error_handlers(app)

    dist = settings.frontend_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            # Client-side routing only: never answer API paths or file-like requests with the SPA shell.
            if path.startswith("api") or ".." in path or Path(path).suffix:
                raise HTTPException(404)
            return FileResponse(dist / "index.html")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return app
