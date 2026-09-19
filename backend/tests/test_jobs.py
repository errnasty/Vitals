"""The cron job: capture to bronze, then refresh silver.

The two halves belong together, and the failure mode of them coming apart is silent —
bronze keeps filling, the dashboard keeps serving last week's numbers, and nothing
anywhere reports an error. So the wiring is tested rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import AppUser, MetricDaily
from vitals.ingest.raw_store import RawRecord, RawStore
from vitals.normalize import canonical as c
from vitals.sources.base import FAILED, SUCCESS, SyncOutcome
from vitals.workers import jobs


class _Maker:
    """Stands in for `get_sessionmaker()`, handing back the test's own session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: Any) -> bool:
        return False


async def _seed(session: AsyncSession, user: AppUser, *, day: date) -> None:
    await RawStore(session, user_id=user.id, source="garmin").store(
        [
            RawRecord(
                "rhr_daily",
                {"calendarDate": day.isoformat(), "value": 48},
                calendar_date=day,
            )
        ]
    )


def _wire(monkeypatch: pytest.MonkeyPatch, session: AsyncSession, outcome: SyncOutcome) -> None:
    async def fake_incremental(*args: Any, **kwargs: Any) -> SyncOutcome:
        return outcome

    monkeypatch.setattr(jobs, "get_sessionmaker", lambda: _Maker(session))
    monkeypatch.setattr(jobs, "run_incremental", fake_incremental)


async def _daily_rows(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(MetricDaily)) or 0


async def test_a_successful_sync_refreshes_silver(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = datetime.now(UTC).date()
    await _seed(pg_session, pg_user, day=today - timedelta(days=1))
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    outcome = await jobs.run_sync(days=7)

    assert outcome.status == SUCCESS
    assert await _daily_rows(pg_session) == 1


async def test_silver_is_left_alone_when_the_sync_failed(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed capture is no basis for recomputing anything."""
    await _seed(pg_session, pg_user, day=datetime.now(UTC).date())
    _wire(monkeypatch, pg_session, SyncOutcome(status=FAILED, detail="rate limited"))

    await jobs.run_sync(days=7)

    assert await _daily_rows(pg_session) == 0


async def test_normalize_can_be_switched_off(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(pg_session, pg_user, day=datetime.now(UTC).date())
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    await jobs.run_sync(days=7, normalize=False)

    assert await _daily_rows(pg_session) == 0


async def test_a_broken_normalizer_does_not_fail_the_sync(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bronze is the copy that cannot be re-fetched; a recompute can always be re-run."""
    await _seed(pg_session, pg_user, day=datetime.now(UTC).date())
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    async def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("normalizer blew up")

    monkeypatch.setattr(jobs, "normalize_silver", explode)

    outcome = await jobs.run_sync(days=7)

    assert outcome.status == SUCCESS


async def test_only_the_synced_window_is_recomputed(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daily cron has no business rebuilding seven years of history every six hours."""
    today = datetime.now(UTC).date()
    await _seed(pg_session, pg_user, day=today - timedelta(days=1))
    await _seed(pg_session, pg_user, day=today - timedelta(days=400))
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=2))

    await jobs.run_sync(days=7)

    days = (await pg_session.execute(select(MetricDaily.calendar_date))).scalars().all()
    assert days == [today - timedelta(days=1)]


async def test_a_missing_account_is_a_warning_not_a_crash(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    outcome = await jobs.run_sync(days=7)

    assert outcome.status == SUCCESS
    assert await _daily_rows(pg_session) == 0


async def test_the_metric_written_is_the_canonical_one(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(pg_session, pg_user, day=datetime.now(UTC).date())
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    await jobs.run_sync(days=7)

    row = await pg_session.scalar(select(MetricDaily))
    assert row is not None
    assert (row.metric, row.value, row.unit) == (c.RESTING_HR, 48.0, "bpm")


async def test_the_brief_is_written_last(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is the only step that can spend money, so it runs after everything it describes."""
    order: list[str] = []

    for name in ("normalize_silver", "recompute_gold", "score_day", "write_brief"):
        original = getattr(jobs, name)

        def wrapper(*args: Any, _name: str = name, _fn: Any = original, **kwargs: Any) -> Any:
            order.append(_name)
            return _fn(*args, **kwargs)

        monkeypatch.setattr(jobs, name, wrapper)

    await _seed(pg_session, pg_user, day=datetime.now(UTC).date() - timedelta(days=1))
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    await jobs.run_sync(days=7)

    assert order == ["normalize_silver", "recompute_gold", "score_day", "write_brief"]


async def test_a_broken_brief_does_not_fail_the_sync(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bronze is already captured by this point, and it is the copy that cannot be refetched."""

    async def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the model layer fell over")

    monkeypatch.setattr(jobs, "write_brief", explode)
    await _seed(pg_session, pg_user, day=datetime.now(UTC).date() - timedelta(days=1))
    _wire(monkeypatch, pg_session, SyncOutcome(status=SUCCESS, stored=1))

    outcome = await jobs.run_sync(days=7)

    assert outcome.status == SUCCESS
    assert await _daily_rows(pg_session) == 1
