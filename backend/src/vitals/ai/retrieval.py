"""Loading the days a question might need, and the ones most like today.

The bridge between `analytics/similar.py`, which knows nothing about databases, and
the Q&A, which must never do arithmetic. Everything that leaves here is either a
number Python computed or a sentence Python wrote.

The feature set is short and fixed. Similarity is only meaningful along axes that
describe a day rather than merely happened on it, and every extra axis dilutes the
ones that matter — twelve numbers already make two days "70% alike" on the strength of
things nobody would call a resemblance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as gold
from vitals.analytics import similar
from vitals.api import format as fmt
from vitals.db.models import DerivedDaily, MetricDaily, VitalsScore
from vitals.normalize import canonical as silver

# What makes one day like another. Silver where the reading itself is the fact,
# gold where the meaning is.
FEATURES: tuple[tuple[str, bool], ...] = (
    (silver.HRV_OVERNIGHT_AVG, False),
    (silver.RESTING_HR, False),
    (silver.SLEEP_DURATION, False),
    (silver.STRESS_AVG, False),
    (silver.STEPS, False),
    (gold.HRV_DEVIATION, True),
    (gold.RHR_DEVIATION, True),
    (gold.SLEEP_DEBT, True),
    (gold.CTL, True),
    (gold.ACWR, True),
    (gold.TSB, True),
)

# How a feature reads in a sentence explaining a resemblance.
FEATURE_PHRASE: dict[str, str] = {
    silver.HRV_OVERNIGHT_AVG: "overnight HRV",
    silver.RESTING_HR: "resting heart rate",
    silver.SLEEP_DURATION: "sleep duration",
    silver.STRESS_AVG: "average stress",
    silver.STEPS: "steps",
    gold.HRV_DEVIATION: "HRV against baseline",
    gold.RHR_DEVIATION: "resting heart rate against baseline",
    gold.SLEEP_DEBT: "sleep debt",
    gold.CTL: "fitness",
    gold.ACWR: "load balance",
    gold.TSB: "form",
}

# Long enough to hold more than one season, short enough that a different athlete's
# days are not offered as resembling this one.
WINDOW_DAYS = 800


@dataclass(frozen=True, slots=True)
class SimilarDay:
    day: date
    score: str | None
    # "alike on overnight HRV, resting heart rate and form"
    alike: str
    # "unlike on steps"
    unlike: str
    shared: int


async def features(
    session: AsyncSession, *, user_id: uuid.UUID, end: date, days: int = WINDOW_DAYS
) -> dict[date, dict[str, float]]:
    """Every day's feature vector, as far back as the window reaches."""
    start = end - timedelta(days=days)
    rows: dict[date, dict[str, float]] = {}

    silver_names = [name for name, is_gold in FEATURES if not is_gold]
    gold_names = [name for name, is_gold in FEATURES if is_gold]

    for model, names in ((MetricDaily, silver_names), (DerivedDaily, gold_names)):
        found = (
            await session.execute(
                select(model.calendar_date, model.metric, model.value).where(
                    model.user_id == user_id,
                    model.metric.in_(names),
                    model.calendar_date >= start,
                    model.calendar_date <= end,
                )
            )
        ).all()
        for day, metric, value in found:
            rows.setdefault(day, {})[metric] = float(value)

    return rows


def _listed(names: tuple[str, ...]) -> str:
    """ "a, b and c" — written here so no screen joins a list itself."""
    words = [FEATURE_PHRASE.get(name, name) for name in names]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


async def similar_days(
    session: AsyncSession, *, user_id: uuid.UUID, target: date, limit: int = 3
) -> list[SimilarDay]:
    """The days most like `target`, with what made them alike, in words."""
    rows = await features(session, user_id=user_id, end=target)
    neighbours = similar.nearest(rows, target=target, limit=limit)
    if not neighbours:
        return []

    scores = {
        day: value
        for day, value in (
            await session.execute(
                select(VitalsScore.calendar_date, VitalsScore.score).where(
                    VitalsScore.user_id == user_id,
                    VitalsScore.calendar_date.in_([n.day for n in neighbours]),
                )
            )
        ).all()
    }

    return [
        SimilarDay(
            day=n.day,
            score=None if n.day not in scores else fmt.number(scores[n.day]),
            alike=_listed(n.alike),
            unlike=_listed(n.unlike),
            shared=n.shared,
        )
        for n in neighbours
    ]
