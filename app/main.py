"""Main FastAPI application for Vaari."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match, Route

import app.models  # ensure models are registered
from app.config import settings
from app.db import get_engine, get_session_factory
from app.errors import setup_error_handlers
from app.intake.probe import start_probe_in_background
from app.logging_setup import RequestContextMiddleware, configure_logging, log_event
from app.migrate import ensure_schema
from app.ratelimit import RateLimitMiddleware
from app.routes.auth import router as auth_router
from app.routes.common import get_or_create_home_centre
from app.routes.dashboard import router as dashboard_router
from app.routes.driver import router as driver_router
from app.routes.health import router as health_router
from app.routes.intake import router as intake_router
from app.routes.machines import router as machines_router
from app.routes.plots import router as plots_router
from app.routes.records import router as records_router
from app.routes.requests import router as requests_router
from app.routes.schedule import router as schedule_router
from app.routes.slots import router as slots_router
from app.security_headers import ConfiguredCORSMiddleware, SecurityHeadersMiddleware
from app.startup_checks import UnsafeConfigError, enforce_startup_checks


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        enforce_startup_checks(settings)
    except UnsafeConfigError as exc:
        # One clear line for whoever reads the container logs, before uvicorn prints the traceback.
        logging.getLogger("vaari").error(str(exc), extra={"fields": {"event": "refused_to_start"}})
        raise
    revision = ensure_schema(get_engine())
    log_event("startup", event="startup", env=settings.env, auth=settings.auth_mode, reader=settings.reader, revision=revision)
    if settings.reader_probe:
        start_probe_in_background(settings)
    session_factory = get_session_factory()
    with session_factory() as session:
        get_or_create_home_centre(session)
        session.commit()
    yield


app = FastAPI(title="Vaari Backend", version="0.1", lifespan=lifespan)

setup_error_handlers(app)
app.add_middleware(RateLimitMiddleware)
# Cross-origin calls only from VAARI_CORS_ORIGINS. Same-origin use (the normal case) needs none.
app.add_middleware(ConfiguredCORSMiddleware)
# Request IDs, access logs and the last-resort 500 handler wrap everything below.
app.add_middleware(RequestContextMiddleware)
# Added last so it wraps everything, including rate-limit, CORS and 500 responses.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(requests_router, prefix="/api")
app.include_router(machines_router, prefix="/api")
app.include_router(plots_router, prefix="/api")
app.include_router(schedule_router, prefix="/api")
app.include_router(slots_router, prefix="/api")
app.include_router(driver_router, prefix="/api")
app.include_router(records_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(intake_router, prefix="/api")

web_dist = Path(__file__).parent.parent / "web" / "dist"


class NonApiRoute(Route):
    def matches(self, scope):
        if scope["type"] == "http" and (
            scope["path"] == "/api" or scope["path"].startswith("/api/")
        ):
            return Match.NONE, {}
        return super().matches(scope)


async def spa_fallback(request: Request):
    full_path = request.path_params.get("full_path", "")
    file_path = web_dist / full_path
    if full_path and file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    index_file = web_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise StarletteHTTPException(
        status_code=404,
        detail="Frontend not built. Run 'python tasks.py build-web'.",
    )


app.router.routes.append(
    NonApiRoute("/{full_path:path}", endpoint=spa_fallback, methods=["GET", "HEAD"])
)
if (web_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")
