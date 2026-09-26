"""Loading silver into the shape the analytics modules actually want.

Two decisions do most of the work here.

**Dense, not sparse.** A series is one slot per calendar day with `None` for the days
nothing was recorded, so a 42-day window is a slice rather than a date calculation, and
a gap is visible instead of silently closing up. Rolling statistics over a sparse dict
are where off-by-a-week bugs live.

**History beyond the window being written.** Computing yesterday's chronic training
load needs the six weeks before it, so loading always reaches back by the longest
window any metric declares. Ask for the last 7 days and you still get a correct CTL,
because the 42 days behind it came too.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as d
from vitals.db.models import Activity, ActivityDetail, SleepSession
from vitals.normalize.resolver import DEFAULT_PREFERENCE, daily_series

# The longest lookback anything declares. Loading reaches back this far behind the
# window being computed so the first day of that window is as correct as the last.
MAX_WINDOW_DAYS = max(definition.window_days for definition in d.REGISTRY.values())


@dataclass(frozen=True, slots=True)
class Series:
    """One metric, one slot per day from `start` to `end` inclusive."""

    metric: str
    unit: str
    start: date
    values: list[float | None]

    @property
    def end(self) -> date:
        return self.start + timedelta(days=len(self.values) - 1)

    def index(self, day: date) -> int | None:
        offset = (day - self.start).days
        return offset if 0 <= offset < len(self.values) else None

    def at(self, day: date) -> float | None:
        offset = self.index(day)
        return None if offset is None else self.values[offset]

    def window(self, day: date, days: int) -> list[float | None]:
        """The `days` slots ending on `day`, inclusive. Short at the series start."""
        offset = self.index(day)
        if offset is None:
            return []
        first = max(0, offset - days + 1)
        return self.values[first : offset + 1]

    def present(self, day: date, days: int) -> list[float]:
        """Only the days that actually hold an observation."""
        return [v for v in self.window(day, days) if v is not None]

    def filled(self, day: date, days: int, fill: float = 0.0) -> list[float]:
        """The window with gaps replaced — for quantities where absence means zero."""
        return [fill if v is None else v for v in self.window(day, days)]


@dataclass(frozen=True, slots=True)
class Night:
    """The parts of a sleep session that `metric_daily` cannot carry."""

    calendar_date: date
    started_at: datetime | None
    ended_at: datetime | None
    duration_s: int | None
    deep_s: int | None
    rem_s: int | None

    @property
    def midpoint_minutes(self) -> float | None:
        """Minutes past midnight UTC of the middle of the night.

        The number sleep consistency is the spread of. Taken from the UTC instants
        rather than the provider's local fields, which the library documents as
        double-offset on some accounts.
        """
        if self.started_at is None or self.ended_at is None:
            return None
        middle = self.started_at + (self.ended_at - self.started_at) / 2
        return middle.hour * 60 + middle.minute + middle.second / 60


@dataclass(frozen=True, slots=True)
class DayRecording:
    """One day's recordings, reduced to what a daily metric can use.

    Decoupling is taken from the longest qualifying activity rather than averaged
    across the day. It is a property of one sustained effort; averaging a two-hour
    ride with a twenty-minute warm-up jog produces a number describing neither.
    """

    decoupling_pct: float | None
    ascent_m: float | None


@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything one analytics run reads, loaded once."""

    start: date
    end: date
    series: dict[str, Series]
    nights: dict[date, Night]
    # Sum of every activity's training load, by day. Absent means a rest day.
    activity_load: dict[date, float]
    activity_count: dict[date, int]
    # What the FIT files added, by day. Empty for anyone whose recordings have not
    # been downloaded yet, which is why nothing downstream may require it.
    recordings: dict[date, DayRecording] = field(default_factory=dict)

    def get(self, metric: str) -> Series:
        return self.series[metric]

    def days(self) -> list[date]:
        span = (self.end - self.start).days
        return [self.start + timedelta(days=offset) for offset in range(span + 1)]


def _dense(points: Sequence[tuple[date, float]], start: date, end: date) -> list[float | None]:
    span = (end - start).days + 1
    values: list[float | None] = [None] * span
    for day, value in points:
        offset = (day - start).days
        if 0 <= offset < span:
            values[offset] = value
    return values


async def load_inputs(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    metrics: Sequence[str],
    start: date,
    end: date,
    prefer: Sequence[str] = DEFAULT_PREFERENCE,
    lookback_days: int = MAX_WINDOW_DAYS,
) -> Inputs:
    """Load every series, night and activity the run needs, plus its history."""
    from vitals.normalize import canonical as silver

    history_start = start - timedelta(days=lookback_days)

    series: dict[str, Series] = {}
    for metric in metrics:
        points = await daily_series(
            session,
            user_id=user_id,
            metric=metric,
            start=history_start,
            end=end,
            prefer=prefer,
        )
        series[metric] = Series(
            metric=metric,
            unit=silver.unit_for(metric),
            start=history_start,
            values=_dense([(p.calendar_date, p.value) for p in points], history_start, end),
        )

    nights = await _load_nights(session, user_id=user_id, start=history_start, end=end)
    load, counts = await _load_activity_load(session, user_id=user_id, start=history_start, end=end)
    recordings = await _load_recordings(session, user_id=user_id, start=history_start, end=end)

    return Inputs(
        start=start,
        end=end,
        series=series,
        nights=nights,
        activity_load=load,
        activity_count=counts,
        recordings=recordings,
    )


async def _load_recordings(
    session: AsyncSession, *, user_id: uuid.UUID, start: date, end: date
) -> dict[date, DayRecording]:
    """Per-day facts from the FIT files, joined back through the activity.

    Joined rather than keyed by date directly, because `activity_detail` deliberately
    holds no date of its own: the activity owns when it happened, and storing that
    twice is how the two come to disagree.
    """
    rows = (
        await session.execute(
            select(
                Activity.started_at,
                Activity.duration_s,
                ActivityDetail.decoupling_pct,
                ActivityDetail.ascent_m,
            )
            .join(ActivityDetail, ActivityDetail.activity_id == Activity.id)
            .where(Activity.user_id == user_id, Activity.started_at.is_not(None))
        )
    ).all()

    longest: dict[date, float] = {}
    decoupling: dict[date, float] = {}
    ascent: dict[date, float] = {}

    for started_at, duration_s, decouple, climb in rows:
        day = started_at.date()
        if day < start or day > end:
            continue
        if climb is not None:
            ascent[day] = ascent.get(day, 0.0) + climb
        if decouple is not None and (duration_s or 0.0) >= longest.get(day, -1.0):
            longest[day] = duration_s or 0.0
            decoupling[day] = decouple

    return {
        day: DayRecording(decoupling_pct=decoupling.get(day), ascent_m=ascent.get(day))
        for day in set(decoupling) | set(ascent)
    }


async def _load_nights(
    session: AsyncSession, *, user_id: uuid.UUID, start: date, end: date
) -> dict[date, Night]:
    statement = (
        select(
            SleepSession.calendar_date,
            SleepSession.started_at,
            SleepSession.ended_at,
            SleepSession.duration_s,
            SleepSession.deep_s,
            SleepSession.rem_s,
        )
        .where(
            SleepSession.user_id == user_id,
            SleepSession.calendar_date >= start,
            SleepSession.calendar_date <= end,
        )
        .order_by(SleepSession.calendar_date)
    )
    rows = (await session.execute(statement)).all()
    return {
        row[0]: Night(
            calendar_date=row[0],
            started_at=row[1],
            ended_at=row[2],
            duration_s=row[3],
            deep_s=row[4],
            rem_s=row[5],
        )
        for row in rows
    }


async def _load_activity_load(
    session: AsyncSession, *, user_id: uuid.UUID, start: date, end: date
) -> tuple[dict[date, float], dict[date, int]]:
    """Every activity's load, bucketed by the UTC day it started.

    Garmin's own `activityTrainingLoad` is used where present. Where it is not — an
    older device, a manually entered session — the fallback is Banister's TRIMP from
    duration and average heart rate, which is the quantity Garmin's own number is a
    refinement of.
    """
    statement = select(
        Activity.started_at, Activity.duration_s, Activity.avg_hr, Activity.training_load
    ).where(Activity.user_id == user_id, Activity.started_at.is_not(None))
    rows = (await session.execute(statement)).all()

    load: dict[date, float] = {}
    counts: dict[date, int] = {}
    for started_at, duration_s, avg_hr, training_load in rows:
        day = started_at.date()
        if day < start or day > end:
            continue
        value = training_load
        if value is None:
            value = trimp(duration_s=duration_s, avg_hr=avg_hr)
        if value is None:
            continue
        load[day] = load.get(day, 0.0) + value
        counts[day] = counts.get(day, 0) + 1
    return load, counts


# Banister's constants for the exponential heart-rate weighting. The 1.92 is the male
# coefficient (1.67 female); at the resolution this feeds it changes ranking, not
# conclusions, and a per-user value belongs in the phase-8 response profile.
TRIMP_EXPONENT = 1.92
RESTING_HR_DEFAULT = 60.0
MAX_HR_DEFAULT = 190.0


def trimp(
    *,
    duration_s: float | None,
    avg_hr: float | None,
    resting_hr: float = RESTING_HR_DEFAULT,
    max_hr: float = MAX_HR_DEFAULT,
) -> float | None:
    """Banister TRIMP: minutes weighted by how hard the heart was working.

    Returns None rather than a zero when either input is missing, so a session with no
    heart rate is absent from the load series instead of being counted as an easy one.
    """
    import math

    if duration_s is None or avg_hr is None or max_hr <= resting_hr:
        return None
    reserve = (avg_hr - resting_hr) / (max_hr - resting_hr)
    if reserve <= 0:
        return None
    minutes = duration_s / 60.0
    return minutes * reserve * 0.64 * math.exp(TRIMP_EXPONENT * reserve)
