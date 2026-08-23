"""Just-in-time provisioning of the local user row, against a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support import EMAIL, USER_ID, hs256, local_settings
from vitals.auth.errors import NotAllowed
from vitals.auth.users import sync_user
from vitals.auth.verifier import TokenVerifier
from vitals.db.models import AppUser


async def _principal(**overrides: object):
    return await TokenVerifier(local_settings()).verify(hs256(**overrides))


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(AppUser))).scalar_one()


async def test_first_request_provisions_the_user(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as session:
        user = await sync_user(session, await _principal())

    assert user.id == USER_ID
    assert user.email == EMAIL
    assert user.timezone == "UTC"
    assert user.is_active is True
    assert user.last_seen_at is not None


async def test_repeated_requests_reuse_the_row(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    principal = await _principal()
    async with sessionmaker() as session:
        first = await sync_user(session, principal)
        created = first.created_at
        await sync_user(session, principal)
        assert await _count(session) == 1

    async with sessionmaker() as session:
        again = await sync_user(session, principal)
        assert again.created_at == created


async def test_last_seen_is_not_written_on_every_request(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Ordinary traffic should be a read, not a write per request."""
    principal = await _principal()
    async with sessionmaker() as session:
        first = await sync_user(session, principal)
        seen = first.last_seen_at
        second = await sync_user(session, principal)

    assert second.last_seen_at == seen


async def test_stale_last_seen_is_refreshed(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    principal = await _principal()
    async with sessionmaker() as session:
        user = await sync_user(session, principal)
        user.last_seen_at = datetime.now(UTC) - timedelta(hours=2)
        await session.commit()

        refreshed = await sync_user(session, principal)

    assert refreshed.last_seen_at is not None
    assert datetime.now(UTC) - refreshed.last_seen_at.replace(tzinfo=UTC) < timedelta(minutes=1)


async def test_a_changed_email_is_mirrored(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as session:
        await sync_user(session, await _principal())
        updated = await sync_user(session, await _principal(email="new@example.com"))

    assert updated.email == "new@example.com"


async def test_a_deactivated_user_is_refused(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A local kill switch that keeps working when Supabase is unreachable."""
    principal = await _principal()
    async with sessionmaker() as session:
        user = await sync_user(session, principal)
        user.is_active = False
        await session.commit()

        with pytest.raises(NotAllowed):
            await sync_user(session, principal)


async def test_an_address_belonging_to_another_account_is_refused(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A Supabase account deleted and recreated gets a new `sub` with the same email.

    Moving the address onto the new id would silently orphan the old account's history,
    so the request is refused and a human decides which row is real.
    """
    import uuid

    async with sessionmaker() as session:
        await sync_user(session, await _principal())

        with pytest.raises(NotAllowed, match="already registered"):
            await sync_user(session, await _principal(sub=str(uuid.uuid4())))

        assert await _count(session) == 1
