"""Loading the data, running the analysis, and storing what it found.

The statistics are argued with next door, in `test_insights_analysis`. What matters
here is the plumbing around them: that too little logged data is a refusal rather than
an error, that a finding which stops holding actually disappears, and that the
denominator survives the round trip — a stored finding without the number of tests
behind it cannot be read honestly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, USER_ID
from vitals.db.models import AppUser, DayContext, Insight, MetricDaily
from vitals.insights import engine
from vitals.normalize import canonical as silver

END = date(2026, 9, 1)


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


async def _tag(session: AsyncSession, offsets: list[int], *, tag: str = "alcohol") -> None:
    for offset in offsets:
        session.add(
            DayContext(user_id=USER_ID, calendar_date=END - timedelta(days=offset), tag=tag)
        )
    await session.commit()


async def _metric(session: AsyncSession, metric: str, values: dict[int, float]) -> None:
    for offset, value in values.items():
        session.add(
            MetricDaily(
                user_id=USER_ID,
                metric=metric,
                calendar_date=END - timedelta(days=offset),
                source="garmin",
                value=value,
                unit=silver.unit_for(metric),
            )
        )
    await session.commit()


async def test_too_little_logged_is_a_refusal_not_an_error(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """Saying nothing is the correct output, and it has to say why."""
    await _tag(pg_session, [1, 2, 3])

    result = await engine.refresh(pg_session, user_id=USER_ID, today=END)

    assert result.tested == 0
    assert result.tagged_days == 3
    assert result.skipped is not None and str(engine.MIN_TAGGED_DAYS) in result.skipped


async def test_tagged_days_with_no_metrics_to_test_against_is_also_a_refusal(
    pg_session: AsyncSession, user: AppUser
) -> None:
    await _tag(pg_session, list(range(20)))

    result = await engine.refresh(pg_session, user_id=USER_ID, today=END)

    assert result.tested == 0
    assert result.skipped == "no metrics in the window to test against"


async def test_a_real_effect_is_found_and_stored_with_its_denominator(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A planted effect large enough to survive the correction has to come through.

    The values are deliberately separated far beyond the noise: this asserts the
    plumbing carries a finding end to end, not that the test is sensitive.
    """
    # Not every other day: alternating days make lag 0 the exact mirror of lag 1, so
    # the test would pass without the lag ever being read correctly. Irregular
    # spacing means only the day *after* a tagged day drops. Offsets count backwards
    # from END, so the day after the one at offset `o` is offset `o - 1` — which is
    # why the planted drop keys on `offset + 1` being tagged.
    tagged = [0, 3, 4, 9, 12, 13, 18, 21, 22, 27, 30, 31, 36, 39, 40, 45, 48, 49, 54, 57]
    await _tag(pg_session, tagged)
    await _metric(
        pg_session,
        silver.HRV_OVERNIGHT_AVG,
        {offset: (30.0 if (offset + 1) in tagged else 60.0) for offset in range(60)},
    )

    result = await engine.refresh(pg_session, user_id=USER_ID, today=END)

    assert result.found >= 1
    rows = (
        (await pg_session.execute(select(Insight).where(Insight.user_id == USER_ID)))
        .scalars()
        .all()
    )
    stored = [row for row in rows if row.significant]
    assert stored, "a planted effect this large must survive the correction"
    assert [row.lag for row in stored] == [1], "the drop is the day after, not the day of"
    found = stored[0]
    assert found.tag == "alcohol"
    assert found.direction == "lower"
    # The denominator: how many tests this run performed, not how many it reported.
    assert found.tested == result.tested >= len(rows)


async def test_a_finding_that_no_longer_holds_disappears(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The one failure mode that would make this actively misleading.

    An upsert would leave last month's conclusion on screen for a pair this run did
    not even report on. The write is a delete-and-rewrite precisely so it cannot.
    """
    pg_session.add(
        Insight(
            id=uuid.uuid4(),
            user_id=USER_ID,
            tag="travel",
            metric=silver.RESTING_HR,
            lag=0,
            n_with=9,
            n_without=40,
            mean_with=60.0,
            mean_without=55.0,
            delta=5.0,
            effect=0.8,
            p_value=0.001,
            significant=True,
            tested=120,
            window_start=END - timedelta(days=400),
            window_end=END,
            computed_at=datetime.now(UTC),
        )
    )
    await pg_session.commit()

    tagged = list(range(0, 60, 2))
    await _tag(pg_session, tagged)
    await _metric(
        pg_session,
        silver.HRV_OVERNIGHT_AVG,
        {offset: (30.0 if (offset + 1) in tagged else 60.0) for offset in range(60)},
    )

    await engine.refresh(pg_session, user_id=USER_ID, today=END)

    survivors = (
        (
            await pg_session.execute(
                select(Insight).where(Insight.user_id == USER_ID, Insight.tag == "travel")
            )
        )
        .scalars()
        .all()
    )
    assert survivors == [], "a stale conclusion must not outlive the run that dropped it"
