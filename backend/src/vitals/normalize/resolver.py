"""Reading silver when more than one source has an opinion.

`metric_daily` deliberately keeps one row per source, so a day the watch was charging
and the phone was in a pocket holds both readings. Something has to choose between
them at read time, and this is that something: a fixed preference order, applied per
day, so a gap in the preferred source falls through to the next one instead of leaving
a hole.

Garmin leads because it is the device actually on the wrist overnight, which is where
every recovery metric comes from. Apple Health (phase 10) fills the days it wasn't.

This is the only place that ranking lives. Phase 4 asks for a series and gets one
value per day; it never learns that sources exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Case, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import MetricDaily

# Most-trusted first.
DEFAULT_PREFERENCE: tuple[str, ...] = ("garmin", "healthkit")


@dataclass(frozen=True, slots=True)
class Point:
    calendar_date: date
    value: float
    unit: str
    source: str


def _rank(prefer: Sequence[str]) -> Case[int]:
    """Order sources by preference; anything unlisted sorts last."""
    return case(
        {source: index for index, source in enumerate(prefer)},
        value=MetricDaily.source,
        else_=len(prefer),
    )


async def daily_series(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    metric: str,
    start: date | None = None,
    end: date | None = None,
    prefer: Sequence[str] = DEFAULT_PREFERENCE,
) -> list[Point]:
    """One value per day, best available source, ascending by date."""
    statement = select(
        MetricDaily.calendar_date, MetricDaily.value, MetricDaily.unit, MetricDaily.source
    ).where(MetricDaily.user_id == user_id, MetricDaily.metric == metric)
    if start is not None:
        statement = statement.where(MetricDaily.calendar_date >= start)
    if end is not None:
        statement = statement.where(MetricDaily.calendar_date <= end)

    # DISTINCT ON keeps the first row per day under this ORDER BY — which is the
    # preferred source, by construction.
    statement = statement.order_by(MetricDaily.calendar_date, _rank(prefer)).distinct(
        MetricDaily.calendar_date
    )

    rows = (await session.execute(statement)).all()
    return [
        Point(calendar_date=day, value=value, unit=unit, source=source)
        for day, value, unit, source in rows
    ]


async def available_metrics(
    session: AsyncSession, *, user_id: uuid.UUID
) -> dict[str, tuple[date, date, int]]:
    """Every metric held, with its first day, last day and day count.

    The honest answer to "what can this account actually compute", and what the CLI
    prints after a normalize run.
    """
    statement = (
        select(
            MetricDaily.metric,
            func.min(MetricDaily.calendar_date),
            func.max(MetricDaily.calendar_date),
            func.count(func.distinct(MetricDaily.calendar_date)),
        )
        .where(MetricDaily.user_id == user_id)
        .group_by(MetricDaily.metric)
        .order_by(MetricDaily.metric)
    )
    rows = (await session.execute(statement)).all()
    return {metric: (first, last, days) for metric, first, last, days in rows}
