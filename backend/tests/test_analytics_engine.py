"""The analytics engine, against a real Postgres.

The modules are tested on their own in `test_analytics_modules.py`; what is under test
here is the engine's own job — choosing the window, turning an observation count into
a coverage fraction, and upserting idempotently.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as d
from vitals.analytics import recompute
from vitals.db.models import AppUser, DerivedDaily, MetricDaily, SleepSession
from vitals.normalize import canonical as silver

END = date(2026, 8, 21)


async def _seed_days(
    session: AsyncSession, user: AppUser, *, days: int, metric: str, value: float
) -> None:
    session.add_all(
        [
            MetricDaily(
                user_id=user.id,
                metric=metric,
                calendar_date=END - timedelta(days=offset),
                source="garmin",
                value=value,
                unit=silver.unit_for(metric),
            )
            for offset in range(days)
        ]
    )
    await session.commit()


async def _derived(session: AsyncSession, metric: str, day: date = END):
    return await session.scalar(
        select(DerivedDaily).where(DerivedDaily.metric == metric, DerivedDaily.calendar_date == day)
    )


async def _count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(DerivedDaily)) or 0


async def test_no_silver_means_no_work_and_no_crash(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """A brand-new account is the normal starting state, not an error."""
    result = await recompute(pg_session, user_id=pg_user.id)

    assert result.empty
    assert await _count(pg_session) == 0


async def test_the_default_window_is_whatever_silver_covers(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _seed_days(pg_session, pg_user, days=10, metric=silver.STEPS, value=9000)

    result = await recompute(pg_session, user_id=pg_user.id)

    assert result.start == END - timedelta(days=9)
    assert result.end == END
    assert result.days == 10


async def test_derived_values_are_written_with_their_unit(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _seed_days(pg_session, pg_user, days=10, metric=silver.STEPS, value=9000)

    await recompute(pg_session, user_id=pg_user.id)
    row = await _derived(pg_session, d.STEPS_7D)

    assert row is not None
    assert row.value == pytest.approx(9000.0)
    assert row.unit == d.unit_for(d.STEPS_7D)


async def test_coverage_is_observations_over_the_declared_window(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Seven days of a metric that claims a 42-day window is a sixth of a claim."""
    await _seed_days(pg_session, pg_user, days=7, metric=silver.STEPS, value=9000)

    await recompute(pg_session, user_id=pg_user.id)
    ctl = await _derived(pg_session, d.CTL)

    assert ctl is not None
    assert ctl.inputs == 7
    assert ctl.coverage == pytest.approx(7 / d.window_for(d.CTL))


async def test_coverage_never_exceeds_one(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _seed_days(pg_session, pg_user, days=60, metric=silver.STEPS, value=9000)

    await recompute(pg_session, user_id=pg_user.id)
    steps = await _derived(pg_session, d.STEPS_7D)

    assert steps is not None and steps.coverage == 1.0


async def test_recomputing_twice_changes_nothing(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Gold is a projection of silver, exactly as silver is a projection of bronze."""
    await _seed_days(pg_session, pg_user, days=20, metric=silver.STEPS, value=9000)

    await recompute(pg_session, user_id=pg_user.id)
    first = await _count(pg_session)
    await recompute(pg_session, user_id=pg_user.id)

    assert await _count(pg_session) == first


async def test_a_changed_formula_updates_in_place(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _seed_days(pg_session, pg_user, days=20, metric=silver.STEPS, value=9000)
    await recompute(pg_session, user_id=pg_user.id)

    await pg_session.execute(
        DerivedDaily.__table__.update().where(DerivedDaily.metric == d.STEPS_7D).values(value=1.0)
    )
    await pg_session.commit()

    await recompute(pg_session, user_id=pg_user.id)
    row = await _derived(pg_session, d.STEPS_7D)

    assert row is not None and row.value == pytest.approx(9000.0)


async def test_the_window_can_be_narrowed_without_breaking_the_history(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """A daily cron recomputes a week, and that week's fitness still knows about six."""
    await _seed_days(pg_session, pg_user, days=60, metric=silver.STEPS, value=9000)

    result = await recompute(pg_session, user_id=pg_user.id, start=END - timedelta(days=2))

    assert result.days == 3
    ctl = await _derived(pg_session, d.CTL)
    assert ctl is not None
    # 42 days of history were loaded even though only 3 days were written.
    assert ctl.inputs == d.window_for(d.CTL)


async def test_a_dry_run_writes_nothing(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _seed_days(pg_session, pg_user, days=20, metric=silver.STEPS, value=9000)

    result = await recompute(pg_session, user_id=pg_user.id, dry_run=True)

    assert result.rows > 0
    assert await _count(pg_session) == 0


async def test_every_written_metric_is_declared(pg_session: AsyncSession, pg_user: AppUser) -> None:
    """The vocabulary phase 5 reads against."""
    await _seed_days(pg_session, pg_user, days=60, metric=silver.STEPS, value=9000)
    await _seed_days(pg_session, pg_user, days=60, metric=silver.RESTING_HR, value=48)
    await _seed_days(pg_session, pg_user, days=60, metric=silver.HRV_OVERNIGHT_AVG, value=62)
    await _seed_days(pg_session, pg_user, days=60, metric=silver.WEIGHT, value=72)

    await recompute(pg_session, user_id=pg_user.id)

    metrics = (await pg_session.execute(select(DerivedDaily.metric).distinct())).scalars().all()
    assert metrics
    for metric in metrics:
        assert metric in d.REGISTRY


async def test_a_failing_module_does_not_sink_the_run(
    pg_session: AsyncSession, pg_user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad formula must not cost the other four their output."""
    from vitals.analytics import engine

    def explode(inputs, day):
        raise RuntimeError("bad formula")

    await _seed_days(pg_session, pg_user, days=20, metric=silver.STEPS, value=9000)
    monkeypatch.setattr(engine, "MODULES", (("boom", explode), *engine.MODULES))

    result = await recompute(pg_session, user_id=pg_user.id)

    assert result.rows > 0
    assert await _derived(pg_session, d.STEPS_7D) is not None


async def test_sleep_structure_reaches_gold_from_its_own_table(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Efficiency and the stage split live only in `sleep_session`, not in metric_daily."""
    start = datetime(2026, 8, 20, 23, 0, tzinfo=UTC)
    pg_session.add(
        SleepSession(
            user_id=pg_user.id,
            source="garmin",
            calendar_date=END,
            started_at=start,
            ended_at=start + timedelta(hours=8),
            duration_s=7 * 3600,
            deep_s=int(1.4 * 3600),
            rem_s=int(1.75 * 3600),
        )
    )
    await _seed_days(pg_session, pg_user, days=1, metric=silver.SLEEP_DURATION, value=7 * 3600)

    await recompute(pg_session, user_id=pg_user.id)

    efficiency = await _derived(pg_session, d.SLEEP_EFFICIENCY)
    assert efficiency is not None and efficiency.value == pytest.approx(87.5)
