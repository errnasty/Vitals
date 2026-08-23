from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Keep the settings singleton away from any real .env values during tests.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://vitals:vitals@localhost:5432/vitals_test"
)
os.environ.setdefault("ENVIRONMENT", "local")

# Auth is env-driven, so a developer's real .env would otherwise leak a live Supabase
# project into the test run and make results depend on the machine.
_AUTH_ENV = (
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "VITALS_ALLOWED_EMAILS",
    "VITALS_AUTH_DISABLED",
)


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    from vitals.api.deps import get_verifier
    from vitals.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in _AUTH_ENV:
        monkeypatch.delenv(name, raising=False)

    get_settings.cache_clear()
    get_verifier.cache_clear()
    yield
    get_settings.cache_clear()
    get_verifier.cache_clear()


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A real (SQLite) database for the tables auth touches.

    Postgres-specific behaviour is covered by CI running the migrations against
    pgvector/pg17; this fixture exists so provisioning logic is tested against an
    actual database rather than a mock that agrees with whatever the code does.
    """
    from vitals.db.models import AppUser

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(AppUser.__table__.create)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()
