"""N-of-1: a question written down before the days happen.

What is being tested is mostly the refusals. An experiment that reports a conclusion
from four logged days, or from a window where one arm never filled, is worse than no
experiment — it launders the person forgetting into a finding about their body.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, USER_ID
from vitals.coach import experiments
from vitals.context import store as context_store
from vitals.db.models import ANSWERED, INCONCLUSIVE, RUNNING, AppUser, MetricDaily
from vitals.normalize import canonical as silver

START = date(2026, 8, 1)
DAYS = 21


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


def _proposal() -> experiments.Proposal:
    return experiments.propose(tag="alcohol", metric=silver.HRV_OVERNIGHT_AVG, lag=1, days=DAYS)


async def _log(session: AsyncSession, day: date, tags: list[str]) -> None:
    await context_store.set_tags(
        session,
        user_id=USER_ID,
        on=day,
        tags=[context_store.Tagged(name=name) for name in tags],
    )


async def _hrv(session: AsyncSession, day: date, value: float) -> None:
    session.add(
        MetricDaily(
            user_id=USER_ID,
            metric=silver.HRV_OVERNIGHT_AVG,
            calendar_date=day,
            source="garmin",
            value=value,
            unit="ms",
        )
    )


async def test_the_question_is_written_before_the_days_happen(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The one property that makes this worth more than a correlation."""
    proposal = _proposal()

    row = await experiments.start(pg_session, user_id=USER_ID, proposal=proposal, today=START)

    assert row.status == RUNNING
    assert row.started_on == START
    assert row.ends_on == START + timedelta(days=DAYS - 1)
    assert row.hypothesis == proposal.hypothesis
    assert row.conclusion is None


async def test_only_one_experiment_runs_at_a_time(pg_session: AsyncSession, user: AppUser) -> None:
    """Two changes at once and neither answer means anything."""
    first = await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)

    await pg_session.refresh(first)
    assert first.status == "abandoned"
    running = await experiments.active(pg_session, user_id=USER_ID)
    assert running is not None and running.id != first.id


async def test_a_window_that_has_not_closed_is_not_evaluated(
    pg_session: AsyncSession, user: AppUser
) -> None:
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)

    assert (
        await experiments.evaluate(pg_session, user_id=USER_ID, today=START + timedelta(days=5))
        is None
    )


async def test_a_window_nobody_logged_says_so_rather_than_reporting_nothing_found(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The distinction that keeps this honest: the experiment did not happen, which
    is not the same as the change doing nothing."""
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)
    for offset in range(4):
        await _log(pg_session, START + timedelta(days=offset), ["alcohol"])

    row = await experiments.evaluate(
        pg_session, user_id=USER_ID, today=START + timedelta(days=DAYS + 1)
    )

    assert row is not None
    assert row.status == INCONCLUSIVE
    assert "too few to compare" in (row.conclusion or "")
    assert row.p_value is None


async def test_an_arm_that_never_filled_is_refused(pg_session: AsyncSession, user: AppUser) -> None:
    """Every day tagged means there is nothing to compare against."""
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        await _log(pg_session, day, ["alcohol"])
        await _hrv(pg_session, day + timedelta(days=1), 50.0)
    await pg_session.commit()

    row = await experiments.evaluate(
        pg_session, user_id=USER_ID, today=START + timedelta(days=DAYS + 1)
    )

    assert row is not None
    assert row.status == INCONCLUSIVE
    assert "each side" in (row.conclusion or "")


async def test_a_real_difference_is_answered_with_its_numbers(
    pg_session: AsyncSession, user: AppUser
) -> None:
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        drank = offset % 2 == 0
        await _log(pg_session, day, ["alcohol"] if drank else ["stress"])
        # The morning after drinking is the low one.
        await _hrv(pg_session, day + timedelta(days=1), 38.0 if drank else 62.0)
    await pg_session.commit()

    row = await experiments.evaluate(
        pg_session, user_id=USER_ID, today=START + timedelta(days=DAYS + 1)
    )

    assert row is not None
    assert row.status == ANSWERED
    assert row.significant is True
    assert row.n_with is not None and row.n_with >= experiments.MIN_GROUP
    assert "24.0 ms" in (row.conclusion or "")


async def test_no_difference_is_a_result_and_reads_like_one(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The most likely outcome of any honest experiment. Left as two words it reads
    like a failure rather than the information it is."""
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        drank = offset % 2 == 0
        await _log(pg_session, day, ["alcohol"] if drank else ["stress"])
        await _hrv(pg_session, day + timedelta(days=1), 50.0 + (offset % 3))
    await pg_session.commit()

    row = await experiments.evaluate(
        pg_session, user_id=USER_ID, today=START + timedelta(days=DAYS + 1)
    )

    assert row is not None
    assert row.status == INCONCLUSIVE
    assert row.significant is False
    conclusion = row.conclusion or ""
    assert "inside what chance produces" in conclusion
    assert "neither is a reason to keep worrying" in conclusion


async def test_the_final_day_s_effect_still_has_somewhere_to_land(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A next-day effect needs the morning after the last day, or the window throws
    away the observation it was built to catch."""
    await experiments.start(pg_session, user_id=USER_ID, proposal=_proposal(), today=START)
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        await _log(pg_session, day, ["alcohol"] if offset % 2 == 0 else ["stress"])
        await _hrv(pg_session, day + timedelta(days=1), 38.0 if offset % 2 == 0 else 62.0)
    await pg_session.commit()

    row = await experiments.evaluate(
        pg_session, user_id=USER_ID, today=START + timedelta(days=DAYS + 1)
    )

    assert row is not None
    # 21 days, alternating: 11 tagged. Each of those has a next morning inside the
    # extended window, so all 11 are usable.
    assert (row.n_with or 0) + (row.n_without or 0) == DAYS
