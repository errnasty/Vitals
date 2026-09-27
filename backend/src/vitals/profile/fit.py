"""Measuring the anchors from someone's own history.

Measured, not fitted. Every trait below is a statistic of observations that exist —
the highest heart rate actually recorded, the lowest resting rate actually seen — and
where the observations are not there, the trait is simply absent. Nothing here falls
back to a population default, because a population default wearing a personalised
label is the thing this file is trying to avoid: it would look like evidence and be a
guess, and the scoring curves would treat it exactly as if it were real.

The one trait that is more than a maximum is sleep need, and it is deliberately the
most conservative. It asks which nightly duration this person's own next-day HRV is
best after, over bands wide enough that the answer is not one lucky night, and refuses
to answer at all unless several bands have enough nights to compare.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as gold
from vitals.db.models import Activity, DerivedDaily, MetricDaily, ResponseTrait
from vitals.logging import get_logger
from vitals.normalize import canonical as silver
from vitals.profile import canonical as traits

log = get_logger(__name__)

# How far back to measure. A maximum heart rate from six years ago is not this year's
# maximum heart rate, and a resting floor from a different fitness era is not a floor.
WINDOW_DAYS = 1100

# Sleep-need bands, in hours. Half-hour buckets are narrower than the noise in a
# wrist-measured sleep duration; a full hour is wide enough that each band can
# accumulate enough nights to mean something.
SLEEP_BANDS: tuple[tuple[float, float], ...] = (
    (5.0, 6.0),
    (6.0, 7.0),
    (7.0, 8.0),
    (8.0, 9.0),
    (9.0, 10.0),
)
MIN_NIGHTS_PER_BAND = 10
MIN_BANDS = 3
HOUR = 3600.0

# A resting heart rate is a floor, not a minimum: the single lowest reading in three
# years is as likely to be a sensor artefact as a fitness peak. The fifth percentile
# is low enough to mean "when you are at your best" and robust enough to survive one
# bad morning.
FLOOR_PERCENTILE = 0.05


@dataclass
class FitResult:
    fitted: int = 0
    skipped: dict[str, str] | None = None

    def skip(self, trait: str, why: str) -> None:
        if self.skipped is None:
            self.skipped = {}
        self.skipped[trait] = why


@dataclass(frozen=True, slots=True)
class Measured:
    trait: str
    value: float
    observations: int
    basis: str


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def max_hr(readings: list[float]) -> Measured | None:
    """The highest heart rate actually recorded in an activity.

    The plain maximum rather than a percentile, because this genuinely is an extreme:
    a maximum heart rate is by definition the one time you reached it, and trimming
    the top would systematically under-report it and shift every zone boundary down.
    The protection against a loose-strap spike is the observation floor instead —
    below ten activities there is no trait at all.
    """
    definition = traits.trait_for(traits.MAX_HR)
    if len(readings) < definition.min_observations:
        return None
    return Measured(
        trait=traits.MAX_HR,
        value=max(readings),
        observations=len(readings),
        basis=f"the highest heart rate in {len(readings)} recorded activities",
    )


def resting_floor(readings: list[float]) -> Measured | None:
    """How low your resting heart rate goes when you are rested."""
    definition = traits.trait_for(traits.RESTING_HR_FLOOR)
    if len(readings) < definition.min_observations:
        return None
    return Measured(
        trait=traits.RESTING_HR_FLOOR,
        value=_percentile(readings, FLOOR_PERCENTILE),
        observations=len(readings),
        basis=f"your lowest 5% of {len(readings)} mornings",
    )


def hrv_typical(readings: list[float]) -> Measured | None:
    definition = traits.trait_for(traits.HRV_TYPICAL)
    if len(readings) < definition.min_observations:
        return None
    return Measured(
        trait=traits.HRV_TYPICAL,
        value=_percentile(readings, 0.5),
        observations=len(readings),
        basis=f"the middle of {len(readings)} overnight readings",
    )


def sleep_need(pairs: list[tuple[float, float]]) -> Measured | None:
    """The nightly duration this person's own next-day HRV is best after.

    `pairs` is (seconds asleep, next day's HRV deviation in SD). Bands rather than a
    regression on purpose: the relationship is not linear — more sleep helps until it
    does not — and a straight line through it would confidently report that eleven
    hours is best for everyone who has ever been ill.

    Refuses unless several bands have enough nights. With two bands the answer is
    "whichever of these two you happened to do more of", which is not a finding.
    """
    definition = traits.trait_for(traits.SLEEP_NEED)
    if len(pairs) < definition.min_observations:
        return None

    banded: dict[tuple[float, float], list[float]] = {}
    for seconds, deviation in pairs:
        hours = seconds / HOUR
        for band in SLEEP_BANDS:
            if band[0] <= hours < band[1]:
                banded.setdefault(band, []).append(deviation)
                break

    usable = {band: values for band, values in banded.items() if len(values) >= MIN_NIGHTS_PER_BAND}
    if len(usable) < MIN_BANDS:
        return None

    best = max(usable.items(), key=lambda item: sum(item[1]) / len(item[1]))
    band, values = best
    # The middle of the winning band, not its edge: the evidence says "somewhere in
    # here", and claiming the boundary would be more precision than the band has.
    midpoint = (band[0] + band[1]) / 2

    return Measured(
        trait=traits.SLEEP_NEED,
        value=midpoint * HOUR,
        observations=sum(len(v) for v in usable.values()),
        basis=(
            f"your next-day HRV is highest after {band[0]:.0f}-{band[1]:.0f} hours, "
            f"across {len(values)} such nights"
        ),
    )


# ── loading and storing ─────────────────────────────────────────────────────────


async def _activity_max_hr(
    session: AsyncSession, *, user_id: uuid.UUID, since: date
) -> list[float]:
    rows = (
        await session.execute(
            select(Activity.max_hr).where(
                Activity.user_id == user_id,
                Activity.max_hr.is_not(None),
                Activity.started_at.is_not(None),
                Activity.started_at >= datetime(since.year, since.month, since.day, tzinfo=UTC),
            )
        )
    ).scalars()
    return [float(v) for v in rows if v]


async def _daily(
    session: AsyncSession, *, user_id: uuid.UUID, metric: str, since: date
) -> dict[date, float]:
    rows = (
        await session.execute(
            select(MetricDaily.calendar_date, MetricDaily.value).where(
                MetricDaily.user_id == user_id,
                MetricDaily.metric == metric,
                MetricDaily.calendar_date >= since,
            )
        )
    ).all()
    return {day: float(value) for day, value in rows}


async def _derived(
    session: AsyncSession, *, user_id: uuid.UUID, metric: str, since: date
) -> dict[date, float]:
    rows = (
        await session.execute(
            select(DerivedDaily.calendar_date, DerivedDaily.value).where(
                DerivedDaily.user_id == user_id,
                DerivedDaily.metric == metric,
                DerivedDaily.calendar_date >= since,
            )
        )
    ).all()
    return {day: float(value) for day, value in rows}


async def refresh(
    session: AsyncSession, *, user_id: uuid.UUID, today: date | None = None
) -> FitResult:
    """Re-measure every trait and replace what was stored."""
    end = today or datetime.now(UTC).date()
    since = end - timedelta(days=WINDOW_DAYS)
    result = FitResult()

    measured: list[Measured] = []

    hr_readings = await _activity_max_hr(session, user_id=user_id, since=since)
    rhr = await _daily(session, user_id=user_id, metric=silver.RESTING_HR, since=since)
    hrv = await _daily(session, user_id=user_id, metric=silver.HRV_OVERNIGHT_AVG, since=since)
    sleep = await _daily(session, user_id=user_id, metric=silver.SLEEP_DURATION, since=since)
    deviation = await _derived(session, user_id=user_id, metric=gold.HRV_DEVIATION, since=since)

    # A night's sleep against the *next* morning's HRV deviation. The deviation
    # rather than the raw reading, because it is already measured against this
    # person's own baseline and so is comparable across a fitness era.
    pairs = [
        (seconds, deviation[day + timedelta(days=1)])
        for day, seconds in sleep.items()
        if day + timedelta(days=1) in deviation
    ]

    # Name, attempt and the sentence to show when there is not enough to answer.
    # Missing is a normal state — a fresh account has none of these — so every trait
    # carries its own explanation rather than leaving a screen to invent one.
    for name, candidate, why in (
        (traits.MAX_HR, max_hr(hr_readings), "no recorded activity has a heart rate yet"),
        (
            traits.RESTING_HR_FLOOR,
            resting_floor(list(rhr.values())),
            "not enough mornings recorded",
        ),
        (traits.HRV_TYPICAL, hrv_typical(list(hrv.values())), "not enough overnight readings"),
        (
            traits.SLEEP_NEED,
            sleep_need(pairs),
            "not enough nights across enough different durations",
        ),
    ):
        if candidate is None:
            result.skip(name, why)
        else:
            measured.append(candidate)

    # Replaced wholesale, never merged: a trait that no longer has the observations
    # behind it must disappear rather than linger at last year's value.
    await session.execute(delete(ResponseTrait).where(ResponseTrait.user_id == user_id))
    for item in measured:
        session.add(
            ResponseTrait(
                user_id=user_id,
                trait=item.trait,
                value=item.value,
                unit=traits.trait_for(item.trait).unit,
                observations=item.observations,
                basis=item.basis,
            )
        )
    await session.commit()

    result.fitted = len(measured)
    log.info("profile.fitted", fitted=result.fitted, skipped=sorted(result.skipped or {}))
    return result


async def load(session: AsyncSession, *, user_id: uuid.UUID) -> dict[str, ResponseTrait]:
    """Every trait this person has, by name."""
    rows = (
        (await session.execute(select(ResponseTrait).where(ResponseTrait.user_id == user_id)))
        .scalars()
        .all()
    )
    return {row.trait: row for row in rows}
