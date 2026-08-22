"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vitals import __version__
from vitals.api.routers import health
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


def create_app() -> FastAPI:
    settings = get_settings()
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
    app.include_router(health.router)
    return app


app = create_app()
