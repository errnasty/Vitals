"""Async engine + session factory.

Connect straight to Postgres, never through a transaction pooler: those do not support
prepared statements, which asyncpg creates unconditionally.

`VITALS_DB_POOL_MODE=none` swaps the pool for `NullPool`, so every connection is closed
with the request that opened it. On Railway that is the difference between a service
that can sleep and one that cannot — idleness is judged by outbound packets, and a warm
pool never stops producing them. At one user, reconnecting costs a few milliseconds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from vitals.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if not settings.keeps_connections_warm:
        # NullPool takes no pool_size/max_overflow, and pre-ping is pointless on a
        # connection that was opened for this statement.
        return create_async_engine(settings.database_url, echo=settings.db_echo, poolclass=NullPool)
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    await get_engine().dispose()
    get_engine.cache_clear()
