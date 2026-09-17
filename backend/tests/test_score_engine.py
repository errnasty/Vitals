"""The score engine, against a real Postgres.

The composition is tested pure in `test_score_compose.py`; what is under test here is
storage — that the decomposition survives a round trip, that a recalibration replaces
the waterfall rather than layering a new one on top of the old, and that the whole
thing is as idempotent as the layers below it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as gold
from vitals.db.models import AppUser, DerivedDaily, ScoreContribution, ScorePillar, VitalsScore
from vitals.score import SCORED_METRICS, score

END = date(2026, 8, 21)

VALUES = {
    gold.HRV_DEVIATION: 0.4,
    gold.RHR_DEVIATION: -0.3,
    gold.TSB: -5.0,
    gold.SLEEP_DURATION_7D: 7.2 * 3600,
    gold.SLEEP_DEBT: 4 * 3600,
    gold.SLEEP_CONSISTENCY: 32.0,
    gold.SLEEP_EFFICIENCY: 88.0,
    gold.CTL: 95.0,
    gold.ACWR: 1.05,
    gold.MONOTONY: 1.4,
    gold.VO2MAX_TREND: 52.5,
    gold.ACTIVITY_GUIDELINE_PCT: 140.0,
    gold.STEPS_7D: 9200.0,
}


async def _seed(
    session: AsyncSession,
    user: AppUser,
    *,
    days: int = 400,
    coverage: float = 1.0,
    values: dict[str, float] | None = None,
) -> None:
    rows = []
    for metric, value in (values or VALUES).items():
        for offset in range(days):
            rows.append(
                DerivedDaily(
                    user_id=user.id,
                    metric=metric,
                    calendar_date=END - timedelta(days=offset),
                    value=value * (1 - offset * 0.0005),
                    unit=gold.unit_for(metric),
                    coverage=coverage,
                    inputs=int(coverage * gold.window_for(metric)),
                )
            )
    session.add_all(rows)
    await session.commit()


async def _count(session: AsyncSession, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_no_analytics_means_no_score(pg_session: AsyncSession, pg_user: AppUser) -> None:
    result = await score(pg_session, user_id=pg_user.id)

    assert result.empty
    assert await _count(pg_session, VitalsScore) == 0


async def test_a_score_is_stored_with_its_pillars_and_contributions(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _seed(pg_session, pg_user, days=60)

    result = await score(pg_session, user_id=pg_user.id, start=END, end=END)

    assert result.scored == 1
    row = await pg_session.scalar(select(VitalsScore))
    assert row is not None and 0 <= row.score <= 100 and row.trusted is True
    assert await _count(pg_session, ScorePillar) == 4
    assert await _count(pg_session, ScoreContribution) > 0


async def test_the_stored_effects_reconcile_to_the_stored_score(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """The invariant has to survive the round trip, not just hold in memory."""
    await _seed(pg_session, pg_user, days=60)
    await score(pg_session, user_id=pg_user.id, start=END, end=END)

    row = await pg_session.scalar(select(VitalsScore))
    total = await pg_session.scalar(
        select(func.sum(ScoreContribution.effect)).where(ScoreContribution.calendar_date == END)
    )

    assert row is not None and total is not None
    assert total == pytest.approx(row.score, abs=1e-6)


async def test_scoring_twice_changes_nothing(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _seed(pg_session, pg_user, days=60)

    await score(pg_session, user_id=pg_user.id, start=END - timedelta(days=5))
    counts = [
        await _count(pg_session, model) for model in (VitalsScore, ScorePillar, ScoreContribution)
    ]
    await score(pg_session, user_id=pg_user.id, start=END - timedelta(days=5))

    assert [
        await _count(pg_session, model) for model in (VitalsScore, ScorePillar, ScoreContribution)
    ] == counts


async def test_a_recalibration_replaces_the_waterfall_rather_than_adding_to_it(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """An upsert would leave a removed line behind and break the reconciliation."""
    await _seed(pg_session, pg_user, days=60)
    await score(pg_session, user_id=pg_user.id, start=END, end=END)
    before = await _count(pg_session, ScoreContribution)

    # Drop one input entirely, as removing a contribution would.
    await pg_session.execute(
        DerivedDaily.__table__.delete().where(DerivedDaily.metric == gold.STEPS_7D)
    )
    await pg_session.commit()
    await score(pg_session, user_id=pg_user.id, start=END, end=END)

    after = await _count(pg_session, ScoreContribution)
    assert after == before - 1

    row = await pg_session.scalar(select(VitalsScore))
    total = await pg_session.scalar(select(func.sum(ScoreContribution.effect)))
    assert row is not None and total is not None
    assert total == pytest.approx(row.score, abs=1e-6)


async def test_a_thin_dataset_is_scored_but_flagged(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """A new account should see a number and be told how much to trust it."""
    await _seed(pg_session, pg_user, days=60, coverage=0.3)

    result = await score(pg_session, user_id=pg_user.id, start=END, end=END)

    assert result.scored == 1
    assert result.trusted == 0
    row = await pg_session.scalar(select(VitalsScore))
    assert row is not None and row.trusted is False


async def test_the_window_is_respected(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _seed(pg_session, pg_user, days=60)

    await score(pg_session, user_id=pg_user.id, start=END - timedelta(days=2))

    days = (
        (
            await pg_session.execute(
                select(VitalsScore.calendar_date).order_by(VitalsScore.calendar_date)
            )
        )
        .scalars()
        .all()
    )
    assert days == [END - timedelta(days=2), END - timedelta(days=1), END]


async def test_a_dry_run_writes_nothing(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _seed(pg_session, pg_user, days=60)

    result = await score(pg_session, user_id=pg_user.id, start=END, end=END, dry_run=True)

    assert result.scored == 1
    assert await _count(pg_session, VitalsScore) == 0


async def test_every_scored_metric_is_one_the_engine_declares(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _seed(pg_session, pg_user, days=60)
    await score(pg_session, user_id=pg_user.id, start=END, end=END)

    metrics = (
        (await pg_session.execute(select(ScoreContribution.metric).distinct())).scalars().all()
    )
    assert metrics
    for metric in metrics:
        assert metric in SCORED_METRICS
