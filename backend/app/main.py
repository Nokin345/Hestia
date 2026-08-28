from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth as auth_router
from app.api.routes import chat as chat_router
from app.api.routes import conversations as conversations_router
from app.api.routes import embeddings as embeddings_router
from app.api.routes import kb as kb_router
from app.api.routes import mcp as mcp_router
from app.api.routes import memories as memories_router
from app.api.routes import providers as providers_router
from app.api.routes import sandbox as sandbox_router
from app.api.routes import defaults as defaults_router
from app.api.routes import search as search_router
from app.api.routes import upload as upload_router
from app.auth import current_authenticated
from app.config import get_settings
from app.db import init_db

_PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/auth/login",
    "/api/auth/me",
    "/docs",
    "/redoc",
    "/openapi.json",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA with a catch-all fallback to index.html.

    /api/* and /uploads/* are handled by their routers/mounts registered
    before this; everything else serves static files from dist and falls
    back to index.html so client-side routes (e.g. /settings) survive a
    hard reload.
    """
    if not dist.is_dir():
        return

    index_file = dist / "index.html"
    if not index_file.is_file():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path:
            candidate = (dist / full_path).resolve()
            # Keep resolution inside dist and only serve real files.
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index_file)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_dirs()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if not any(path == p or path.startswith(p + "/") for p in ("/api",)):
            return await call_next(request)
        if path in _PUBLIC_PATHS or path.startswith("/api/auth/login"):
            return await call_next(request)
        if current_authenticated(request):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    app.include_router(auth_router.router)
    app.include_router(conversations_router.router)
    app.include_router(defaults_router.router)
    app.include_router(embeddings_router.router)
    app.include_router(kb_router.router)
    app.include_router(mcp_router.router)
    app.include_router(memories_router.router)
    app.include_router(chat_router.router)
    app.include_router(providers_router.router)
    app.include_router(sandbox_router.router)
    app.include_router(search_router.router)
    app.include_router(upload_router.router)

    app.mount(
        "/uploads",
        StaticFiles(directory=settings.upload_dir),
        name="uploads",
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    _mount_frontend(app, Path(settings.frontend_dist))

    return app


app = create_app()
