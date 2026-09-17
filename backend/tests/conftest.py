from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Keep the settings singleton away from any real .env values during tests.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://vitals:vitals@localhost:5432/vitals_test"
)
os.environ.setdefault("ENVIRONMENT", "local")

# Auth and capability flags are env-driven, so a developer's real .env would otherwise
# leak a live deployment into the test run and make results depend on the machine.
_AUTH_ENV = (
    "VITALS_AUTH_ISSUER",
    "VITALS_AUTH_JWKS_URL",
    "VITALS_AUTH_JWT_SECRET",
    "VITALS_AUTH_AUDIENCE",
    "VITALS_ALLOWED_EMAILS",
    "VITALS_AUTH_DISABLED",
    "VITALS_REQUIRE_PGVECTOR",
    "VITALS_DB_POOL_MODE",
    # Legacy names the settings object still falls back to.
    "SUPABASE_URL",
    "SUPABASE_JWT_SECRET",
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


def _test_database_url() -> str:
    """A database this suite may freely create and drop tables in.

    Never the configured DATABASE_URL itself unless it is already a test database:
    these fixtures drop every table they create, and a developer pointing
    DATABASE_URL at their real deployment should not be one `pytest` away from
    losing it.
    """
    override = os.environ.get("VITALS_TEST_DATABASE_URL")
    if override:
        return override

    from vitals.config import normalize_database_url

    parts = urlsplit(normalize_database_url(os.environ["DATABASE_URL"]))
    name = parts.path.lstrip("/") or "postgres"
    if not name.endswith("_test"):
        name = f"{name}_test"
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


async def _ensure_database(url: str) -> None:
    """Create the test database if it does not exist."""
    parts = urlsplit(url)
    admin = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    name = parts.path.lstrip("/")

    engine = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("select 1 from pg_database where datname = :name"), {"name": name}
            )
            if not exists:
                await connection.execute(text(f'create database "{name}"'))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def pg_engine():
    """A real Postgres, or skip.

    JSONB, ON CONFLICT and NULLS NOT DISTINCT are the mechanics bronze is built on;
    testing them against SQLite would be testing something else entirely. CI provides
    Postgres, and `docker compose up db` provides it locally.
    """
    from vitals.db.models import Base

    url = _test_database_url()
    try:
        await _ensure_database(url)
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - a missing database is a skip, not a failure
        pytest.skip(f"postgres unavailable at {url.rsplit('@', 1)[-1]}: {type(exc).__name__}")

    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncIterator[AsyncSession]:
    """A clean database per test."""
    maker = async_sessionmaker(pg_engine, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        from vitals.db.models import Base

        tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
        await session.execute(text(f"truncate {tables} cascade"))
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def pg_user(pg_session: AsyncSession):
    """An `app_user` row to hang connector data off."""
    from vitals.db.models import AppUser

    user = AppUser(id=uuid.uuid4(), email="owner@example.com")
    pg_session.add(user)
    await pg_session.commit()
    return user
