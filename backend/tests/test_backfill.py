"""The history pull as a cursor: resumable, bounded, and safe to interrupt.

A backfill is minutes of rate-governed requests. The thing worth testing is not that
it fetches — `test_garmin_source.py` covers that — but that stopping it halfway and
starting again picks up exactly where it left off, and that nothing can run away with
a container.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import AppUser, SourceConnection
from vitals.ingest import backfill
from vitals.sources.base import FAILED, SUCCESS, SyncOutcome

TODAY = date(2026, 9, 20)


class FakeSource:
    """Records the windows it was asked for, and answers however the test says."""

    def __init__(self, outcome: SyncOutcome | None = None) -> None:
        self.windows: list[tuple[date, date]] = []
        self.outcome = outcome or SyncOutcome(status=SUCCESS, requests=12)

    async def backfill(self, *, start: date, end: date) -> SyncOutcome:
        self.windows.append((start, end))
        return self.outcome


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch):
    def install(outcome: SyncOutcome | None = None) -> FakeSource:
        fake = FakeSource(outcome)
        monkeypatch.setattr(backfill, "build_garmin_source", lambda *a, **k: fake)
        return fake

    return install


@pytest.fixture
def no_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """The layers above bronze have their own tests; this one is about the cursor."""

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(backfill, "rebuild", noop)


@pytest.fixture
async def connected(pg_session: AsyncSession) -> AppUser:
    user = AppUser(id=uuid.uuid4(), email="owner@example.com")
    pg_session.add(user)
    await pg_session.flush()
    pg_session.add(SourceConnection(user_id=user.id, source="garmin", status="active"))
    await pg_session.commit()
    return user


async def _connection(session: AsyncSession, user_id: uuid.UUID) -> SourceConnection:
    from vitals.ingest.pipeline import connection_for

    row = await connection_for(session, user_id)
    assert row is not None
    return row


async def test_requesting_sets_the_cursor_without_fetching(
    pg_session: AsyncSession, connected: AppUser, source
) -> None:
    """Connect has to return immediately; the pull happens after the response."""
    fake = source()
    await backfill.request(pg_session, user_id=connected.id, years=2, end=TODAY)

    row = await _connection(pg_session, connected.id)
    assert row.backfill_cursor == TODAY
    assert row.backfill_from == TODAY - timedelta(days=730)
    assert fake.windows == []


async def test_it_walks_backwards_so_the_recent_weeks_land_first(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    """An empty dashboard is the problem; the deep history can fill in behind."""
    fake = source()
    await backfill.request(pg_session, user_id=connected.id, years=1, end=TODAY)

    await backfill.advance(pg_session, user_id=connected.id, chunk_days=100)

    assert fake.windows[0][1] == TODAY
    assert fake.windows[0][0] == TODAY - timedelta(days=100)
    # Each window ends where the previous one began: no gaps, no overlap.
    for (start, _), (_, end) in zip(fake.windows, fake.windows[1:], strict=False):
        assert start == end


async def test_it_stops_when_it_reaches_the_requested_start(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    fake = source()
    await backfill.request(pg_session, user_id=connected.id, years=1, end=TODAY)

    result = await backfill.advance(pg_session, user_id=connected.id, chunk_days=100)

    assert result.done
    assert result.days_remaining == 0
    row = await _connection(pg_session, connected.id)
    assert row.backfill_cursor == row.backfill_from
    assert row.backfill_finished_at is not None
    # The last window is clipped rather than overshooting past what was asked for.
    assert fake.windows[-1][0] == row.backfill_from


async def test_a_spent_budget_pauses_rather_than_running_away(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    """The container is awake for the whole of this, and that is the Railway bill."""
    fake = source()
    await backfill.request(pg_session, user_id=connected.id, years=5, end=TODAY)

    ticks = iter([0.0, 0.0, 10.0, 20.0, 999.0])
    result = await backfill.advance(
        pg_session,
        user_id=connected.id,
        chunk_days=100,
        budget_s=30.0,
        monotonic=lambda: next(ticks),
    )

    assert not result.done
    assert result.detail and "next sync" in result.detail
    assert len(fake.windows) < 18  # nowhere near the whole five years


async def test_a_paused_pull_resumes_from_exactly_where_it_stopped(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    """The whole reason it is a cursor rather than an operation."""
    source()
    await backfill.request(pg_session, user_id=connected.id, years=2, end=TODAY)

    ticks = iter([0.0, 0.0, 999.0])
    await backfill.advance(
        pg_session,
        user_id=connected.id,
        chunk_days=100,
        budget_s=1.0,
        monotonic=lambda: next(ticks),
    )
    paused_at = (await _connection(pg_session, connected.id)).backfill_cursor

    second = source()
    await backfill.advance(pg_session, user_id=connected.id, chunk_days=100)

    assert second.windows[0][1] == paused_at
    assert (await _connection(pg_session, connected.id)).backfill_cursor == (
        await _connection(pg_session, connected.id)
    ).backfill_from


async def test_a_failed_window_is_retried_not_skipped(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    """Skipping a rate-limited window would leave a silent hole in the history."""
    source(SyncOutcome(status=FAILED, detail="rate limited"))
    await backfill.request(pg_session, user_id=connected.id, years=1, end=TODAY)

    result = await backfill.advance(pg_session, user_id=connected.id, chunk_days=100)
    assert not result.done
    assert result.detail == "rate limited"
    # The cursor did not move, so the next pass asks for the same window again.
    assert (await _connection(pg_session, connected.id)).backfill_cursor == TODAY

    recovered = source()
    await backfill.advance(pg_session, user_id=connected.id, chunk_days=100)
    assert recovered.windows[0][1] == TODAY


async def test_progress_reports_what_a_screen_can_show(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    source()
    await backfill.request(pg_session, user_id=connected.id, years=1, end=TODAY)

    before = await backfill.progress(pg_session, user_id=connected.id)
    assert before.running and not before.done
    assert before.fraction == pytest.approx(0.0)

    await backfill.advance(pg_session, user_id=connected.id, chunk_days=100)

    after = await backfill.progress(pg_session, user_id=connected.id)
    assert after.done and not after.running
    assert after.fraction == 1.0


async def test_nothing_requested_means_nothing_to_report(
    pg_session: AsyncSession, connected: AppUser
) -> None:
    result = await backfill.progress(pg_session, user_id=connected.id)
    assert result.requested_from is None
    assert result.fraction is None
    assert not result.running


async def test_advancing_without_a_request_does_nothing(
    pg_session: AsyncSession, connected: AppUser, source
) -> None:
    fake = source()
    result = await backfill.advance(pg_session, user_id=connected.id)
    assert fake.windows == []
    assert not result.running


# ── self-healing ────────────────────────────────────────────────────────────────


async def test_an_account_that_never_asked_for_history_gets_asked_for_it(
    pg_session: AsyncSession, connected: AppUser, source
) -> None:
    """The real gap this closes.

    The connect-time request shipped in the same deploy as the migration that added
    these columns, so an account connected fifteen minutes earlier had no cursor to
    write — and nothing afterwards would ever notice. The incremental sync kept
    pulling its trailing week forever and the dashboard showed eight days of data,
    with no error anywhere to explain why.
    """
    source()
    row = await _connection(pg_session, connected.id)
    assert row.backfill_from is None  # exactly the state that account was in

    asked = await backfill.ensure_requested(pg_session, user_id=connected.id, end=TODAY)

    assert asked is True
    row = await _connection(pg_session, connected.id)
    assert row.backfill_from is not None
    assert row.backfill_cursor == TODAY


async def test_it_does_not_re_ask_once_history_has_been_requested(
    pg_session: AsyncSession, connected: AppUser, source, no_rebuild
) -> None:
    """Asking again would rewind a finished pull and re-fetch years for nothing."""
    source()
    await backfill.request(pg_session, user_id=connected.id, years=1, end=TODAY)
    await backfill.advance(pg_session, user_id=connected.id, chunk_days=400)
    finished = await _connection(pg_session, connected.id)
    assert finished.backfill_finished_at is not None

    asked = await backfill.ensure_requested(pg_session, user_id=connected.id, end=TODAY)

    assert asked is False
    again = await _connection(pg_session, connected.id)
    assert again.backfill_cursor == finished.backfill_cursor


async def test_nothing_is_asked_for_an_account_with_no_connection(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    assert await backfill.ensure_requested(pg_session, user_id=pg_user.id) is False
