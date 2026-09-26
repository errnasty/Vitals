"""Whether the dashboard admits its numbers have stopped moving.

The failure this exists for: one endpoint threw an exception the connector did not
catch, the cron died on it, and the sync service sat in CRASHED for six days. The
dashboard showed numbers the whole time — correct ones, from the last good run, with
nothing to say they had stopped. Stale data that looks live is worse than an error,
because an error gets investigated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.api import health_check
from vitals.db.models import AppUser, SourceConnection, SyncRun

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
async def connected(pg_session: AsyncSession) -> AppUser:
    user = AppUser(id=uuid.uuid4(), email="owner@example.com")
    pg_session.add(user)
    await pg_session.flush()
    pg_session.add(SourceConnection(user_id=user.id, source="garmin", status="active"))
    await pg_session.commit()
    return user


async def _run(
    session: AsyncSession, user: AppUser, *, hours_ago: float, status: str = "success"
) -> None:
    session.add(
        SyncRun(
            user_id=user.id,
            source="garmin",
            status=status,
            started_at=NOW - timedelta(hours=hours_ago),
            finished_at=NOW - timedelta(hours=hours_ago),
        )
    )
    await session.commit()


async def test_a_recent_sync_says_nothing_at_all(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    """The normal case carries no UI. An app that warns constantly gets ignored
    exactly when it matters."""
    await _run(pg_session, connected, hours_ago=2)

    result = await health_check.check(pg_session, user_id=connected.id, now=NOW)

    assert result.ok
    assert result.state == "fine"
    assert result.message is None


async def test_a_single_missed_tick_is_not_an_incident(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    """The cron runs every six hours and Railway skips a tick when the previous run
    is still going. That is the design working, not a fault."""
    await _run(pg_session, connected, hours_ago=8)

    assert (await health_check.check(pg_session, user_id=connected.id, now=NOW)).ok


async def test_two_missed_ticks_is_a_pattern(pg_session: AsyncSession, connected: AppUser) -> None:
    await _run(pg_session, connected, hours_ago=20)

    result = await health_check.check(pg_session, user_id=connected.id, now=NOW)

    assert not result.ok
    assert result.state == "stale"
    assert result.message is not None
    assert "20 hours" in result.message


async def test_days_of_silence_says_so_plainly(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    """Six days is exactly what happened. The wording has to make clear that what is
    on screen is not today's."""
    await _run(pg_session, connected, hours_ago=24 * 6)

    result = await health_check.check(pg_session, user_id=connected.id, now=NOW)

    assert result.state == "failing"
    assert result.message is not None
    assert "6 days" in result.message
    assert "not today's" in result.message


async def test_a_failed_run_does_not_reset_the_clock(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    """The question is when data last *arrived*, not when something last tried."""
    await _run(pg_session, connected, hours_ago=30, status="success")
    await _run(pg_session, connected, hours_ago=1, status="failed")

    result = await health_check.check(pg_session, user_id=connected.id, now=NOW)

    assert result.state == "stale"
    assert result.hours_since == 30


async def test_a_partial_run_counts_as_data_arriving(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    """Partial means some endpoints landed. The dashboard is current enough."""
    await _run(pg_session, connected, hours_ago=2, status="partial")

    assert (await health_check.check(pg_session, user_id=connected.id, now=NOW)).ok


async def test_connected_but_never_synced_says_it_is_coming(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    result = await health_check.check(pg_session, user_id=connected.id, now=NOW)

    assert result.state == "never"
    assert result.message is not None
    assert "nothing has synced yet" in result.message.lower()


async def test_no_connection_leaves_it_to_the_connect_prompt(pg_session: AsyncSession) -> None:
    """Two warnings for one problem is worse than one."""
    user = AppUser(id=uuid.uuid4(), email="nobody@example.com")
    pg_session.add(user)
    await pg_session.commit()

    result = await health_check.check(pg_session, user_id=user.id, now=NOW)

    assert result.state == "disconnected"
    assert result.message is None
