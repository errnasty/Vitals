"""Measuring the anchors, and refusing to when the data cannot support them.

The refusals are the tests that matter. A personalised constant is only worth having
if it disappears when the evidence does — a maximum heart rate fitted from three runs
would define every zone boundary in the app, look authoritative, and be wrong.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, USER_ID
from vitals.analytics import canonical as gold
from vitals.db.models import Activity, AppUser, DerivedDaily, MetricDaily, ResponseTrait
from vitals.normalize import canonical as silver
from vitals.profile import canonical as traits
from vitals.profile import fit

TODAY = date(2026, 9, 1)


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


# ── the measurements, as pure functions ─────────────────────────────────────────


def test_max_hr_is_the_actual_maximum_not_a_trimmed_one() -> None:
    """A maximum heart rate is by definition the one time you reached it.

    Trimming the top would systematically under-report it and shift every zone
    boundary down. The protection against a loose strap is the observation floor.
    """
    readings = [170.0] * 20 + [191.0]

    measured = fit.max_hr(readings)

    assert measured is not None
    assert measured.value == 191.0
    assert measured.observations == 21


def test_max_hr_refuses_a_handful_of_activities() -> None:
    assert fit.max_hr([180.0, 185.0, 190.0]) is None


def test_the_resting_floor_survives_one_bad_morning() -> None:
    """A floor, not a minimum: the lowest reading in three years is as likely to be
    a sensor artefact as a fitness peak."""
    readings = [52.0] * 100 + [31.0]

    measured = fit.resting_floor(readings)

    assert measured is not None
    assert measured.value == pytest.approx(52.0)


def test_the_resting_floor_refuses_a_few_mornings() -> None:
    assert fit.resting_floor([50.0] * 5) is None


def test_sleep_need_finds_the_band_the_next_day_is_best_after() -> None:
    """Bands rather than a regression: more sleep helps until it does not, and a
    straight line through that reports eleven hours as best for everyone."""
    pairs: list[tuple[float, float]] = []
    pairs += [(5.5 * 3600, -1.0)] * 20
    pairs += [(6.5 * 3600, -0.4)] * 20
    pairs += [(7.5 * 3600, 0.6)] * 20
    pairs += [(8.5 * 3600, 0.1)] * 20

    measured = fit.sleep_need(pairs)

    assert measured is not None
    assert measured.value == pytest.approx(7.5 * 3600)
    assert "7-8 hours" in measured.basis


def test_sleep_need_refuses_when_only_two_durations_were_ever_slept() -> None:
    """With two bands the answer is 'whichever you happened to do more of'."""
    pairs = [(7.5 * 3600, 0.5)] * 40 + [(8.5 * 3600, 0.2)] * 40

    assert fit.sleep_need(pairs) is None


def test_sleep_need_ignores_a_band_with_too_few_nights() -> None:
    """One brilliant morning after a ten-hour lie-in is not a sleep need."""
    pairs: list[tuple[float, float]] = []
    pairs += [(6.5 * 3600, -0.2)] * 30
    pairs += [(7.5 * 3600, 0.3)] * 30
    pairs += [(8.5 * 3600, 0.2)] * 30
    pairs += [(9.5 * 3600, 5.0)] * 2

    measured = fit.sleep_need(pairs)

    assert measured is not None
    assert measured.value == pytest.approx(7.5 * 3600)


# ── zones ───────────────────────────────────────────────────────────────────────


def test_zones_are_a_percentage_of_a_measured_maximum() -> None:
    """The only personalised part is what the conventional percentages are of."""
    bands = traits.zones(200.0)

    assert [label for label, _, _ in bands] == list(traits.ZONE_LABELS)
    assert bands[0][1] == pytest.approx(100.0)
    assert bands[-1][2] == pytest.approx(200.0)
    # Each zone starts where the last one ended: no gaps to fall into.
    for (_, _, upper), (_, lower, _) in zip(bands, bands[1:], strict=False):
        assert upper == pytest.approx(lower)


# ── storing ─────────────────────────────────────────────────────────────────────


async def _seed(session: AsyncSession) -> None:
    for i in range(40):
        session.add(
            Activity(
                user_id=USER_ID,
                source="garmin",
                external_id=str(i),
                started_at=datetime(2026, 8, 1, tzinfo=UTC) - timedelta(days=i),
                max_hr=170.0 + (i % 12),
                duration_s=3600.0,
            )
        )
    for i in range(60):
        day = TODAY - timedelta(days=i)
        session.add(
            MetricDaily(
                user_id=USER_ID,
                metric=silver.RESTING_HR,
                calendar_date=day,
                source="garmin",
                value=52.0 + (i % 6),
                unit="bpm",
            )
        )
        session.add(
            MetricDaily(
                user_id=USER_ID,
                metric=silver.HRV_OVERNIGHT_AVG,
                calendar_date=day,
                source="garmin",
                value=60.0 + (i % 10),
                unit="ms",
            )
        )
    await session.commit()


async def test_a_fit_writes_traits_with_the_evidence_behind_them(
    pg_session: AsyncSession, user: AppUser
) -> None:
    await _seed(pg_session)

    result = await fit.refresh(pg_session, user_id=USER_ID, today=TODAY)

    assert result.fitted >= 3
    rows = {
        row.trait: row
        for row in (
            (
                await pg_session.execute(
                    select(ResponseTrait).where(ResponseTrait.user_id == USER_ID)
                )
            )
            .scalars()
            .all()
        )
    }
    assert rows[traits.MAX_HR].value == 181.0
    assert rows[traits.MAX_HR].observations == 40
    assert "40 recorded activities" in rows[traits.MAX_HR].basis


async def test_a_trait_that_loses_its_evidence_disappears(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A stale personalised constant is worse than none: the app keeps acting on it
    and nothing says it is out of date."""
    await _seed(pg_session)
    await fit.refresh(pg_session, user_id=USER_ID, today=TODAY)

    # Far enough on that none of that history is inside the measurement window.
    later = TODAY + timedelta(days=fit.WINDOW_DAYS + 300)
    await fit.refresh(pg_session, user_id=USER_ID, today=later)

    rows = (
        (await pg_session.execute(select(ResponseTrait).where(ResponseTrait.user_id == USER_ID)))
        .scalars()
        .all()
    )
    assert rows == []


async def test_a_fresh_account_gets_no_traits_and_a_reason_for_each(
    pg_session: AsyncSession, user: AppUser
) -> None:
    result = await fit.refresh(pg_session, user_id=USER_ID, today=TODAY)

    assert result.fitted == 0
    assert result.skipped is not None
    assert set(result.skipped) == {
        traits.MAX_HR,
        traits.RESTING_HR_FLOOR,
        traits.HRV_TYPICAL,
        traits.SLEEP_NEED,
    }


async def test_sleep_need_pairs_a_night_with_the_next_morning(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """Off by one here and the whole trait measures the wrong thing."""
    for i in range(120):
        day = TODAY - timedelta(days=i)
        hours = 6.5 if i % 3 == 0 else (7.5 if i % 3 == 1 else 8.5)
        pg_session.add(
            MetricDaily(
                user_id=USER_ID,
                metric=silver.SLEEP_DURATION,
                calendar_date=day,
                source="garmin",
                value=hours * 3600,
                unit="s",
            )
        )
        # The morning *after* a 7.5h night is the good one.
        slept_before = 7.5 if (i + 1) % 3 == 1 else 0.0
        pg_session.add(
            DerivedDaily(
                user_id=USER_ID,
                metric=gold.HRV_DEVIATION,
                calendar_date=day,
                value=1.0 if slept_before == 7.5 else -0.5,
                unit="sd",
                inputs=1,
                coverage=1.0,
            )
        )
    await pg_session.commit()

    await fit.refresh(pg_session, user_id=USER_ID, today=TODAY)

    row = await pg_session.scalar(
        select(ResponseTrait).where(
            ResponseTrait.user_id == USER_ID, ResponseTrait.trait == traits.SLEEP_NEED
        )
    )
    assert row is not None
    assert row.value == pytest.approx(7.5 * 3600)
