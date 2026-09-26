"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from vitals import __version__
from vitals.api.routers import auth, context, dashboard, detail, garmin, health
from vitals.auth.errors import AuthError
from vitals.auth.policy import assert_auth_ready
from vitals.config import get_settings
from vitals.db.session import dispose_engine
from vitals.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    log.info(
        "api.startup",
        version=__version__,
        environment=settings.environment,
        service=settings.railway_service,
    )
    yield
    await dispose_engine()
    log.info("api.shutdown")


async def auth_error_handler(request: Request, exc: Exception) -> Response:
    """One error shape for every authentication failure.

    401s carry `WWW-Authenticate` with a machine-readable reason, so the frontend can
    tell "your session expired, sign in again" from "you are not allowed here" without
    parsing prose.
    """
    if not isinstance(exc, AuthError):  # pragma: no cover - registered for AuthError only
        raise exc

    headers: dict[str, str] = {}
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = f'Bearer realm="vitals", error="{exc.code}"'

    log.info(
        "auth.rejected",
        code=exc.code,
        status=exc.status_code,
        path=request.url.path,
        detail=exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "detail": exc.detail},
        headers=headers,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    # Fails the deploy rather than serving health data on a public URL unprotected.
    assert_auth_ready(settings)
    app = FastAPI(
        title="Vitals API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AuthError, auth_error_handler)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(context.router)
    app.include_router(dashboard.router)
    app.include_router(detail.router)
    app.include_router(garmin.router)
    return app


app = create_app()
