"""Running the score over a window and writing it decomposed.

Same shape as the two layers below: load once, walk the days, upsert on the natural
key. The score is a projection of gold in the way gold is a projection of silver, so
all three tables here are disposable — drop them, run `vitals score`, get the same
numbers.

Writing the pillars and contributions is not bookkeeping. It is what makes the number
answerable: the waterfall is a query, the phase-7 model is handed finished arithmetic
rather than a formula, and "why was yesterday worse" has an answer that does not
involve recomputing anything.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.bulk import chunked
from vitals.db.models import DerivedDaily, ScoreContribution, ScorePillar, VitalsScore
from vitals.logging import get_logger
from vitals.score.compose import DayScore, Gold, Reading, compose
from vitals.score.pillars import PILLARS, history_days

log = get_logger(__name__)

# The longest personal-history window any contribution asks for.
MAX_HISTORY_DAYS = max(
    (history_days(c.scorer) for pillar in PILLARS for c in pillar.contributions), default=0
)

# Every gold metric the score reads.
SCORED_METRICS: tuple[str, ...] = tuple(
    dict.fromkeys(c.metric for pillar in PILLARS for c in pillar.contributions)
)


@dataclass
class ScoreResult:
    start: date | None = None
    end: date | None = None
    days: int = 0
    scored: int = 0
    trusted: int = 0
    skipped: int = 0
    mean_score: float | None = None
    mean_coverage: float | None = None
    # pillar -> (days scored, mean score, mean coverage)
    pillars: dict[str, tuple[int, float, float]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.days == 0


async def gold_span(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[date | None, date | None]:
    row = (
        await session.execute(
            select(
                func.min(DerivedDaily.calendar_date), func.max(DerivedDaily.calendar_date)
            ).where(DerivedDaily.user_id == user_id)
        )
    ).one()
    return row[0], row[1]


async def score(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    dry_run: bool = False,
) -> ScoreResult:
    """Compute and store the Vitals Score for one user and window."""
    first, last = await gold_span(session, user_id=user_id)
    if first is None or last is None:
        return ScoreResult()

    window_start = max(start, first) if start else first
    window_end = min(end, last) if end else last
    if window_start > window_end:
        return ScoreResult()

    gold = await _load_gold(
        session,
        user_id=user_id,
        start=window_start - timedelta(days=MAX_HISTORY_DAYS),
        end=window_end,
    )

    result = ScoreResult(start=window_start, end=window_end)
    scores: list[float] = []
    coverages: list[float] = []
    per_pillar: dict[str, list[tuple[float, float]]] = {}
    days: list[DayScore] = []

    cursor = window_start
    while cursor <= window_end:
        result.days += 1
        day = compose(gold, cursor)
        if day is None:
            # Nothing in gold for this day carried enough coverage to say anything.
            result.skipped += 1
        else:
            days.append(day)
            result.scored += 1
            result.trusted += 1 if day.trusted else 0
            scores.append(day.score)
            coverages.append(day.coverage)
            for pillar in day.pillars:
                per_pillar.setdefault(pillar.name, []).append((pillar.score, pillar.coverage))
        cursor += timedelta(days=1)

    if days and not dry_run:
        await _write(session, user_id=user_id, days=days)
        await session.commit()

    result.mean_score = sum(scores) / len(scores) if scores else None
    result.mean_coverage = sum(coverages) / len(coverages) if coverages else None
    result.pillars = {
        name: (
            len(values),
            sum(s for s, _ in values) / len(values),
            sum(c for _, c in values) / len(values),
        )
        for name, values in per_pillar.items()
    }

    log.info(
        "score.finished",
        days=result.days,
        scored=result.scored,
        trusted=result.trusted,
        dry_run=dry_run,
    )
    return result


async def _load_gold(session: AsyncSession, *, user_id: uuid.UUID, start: date, end: date) -> Gold:
    statement = select(
        DerivedDaily.metric, DerivedDaily.calendar_date, DerivedDaily.value, DerivedDaily.coverage
    ).where(
        DerivedDaily.user_id == user_id,
        DerivedDaily.metric.in_(SCORED_METRICS),
        DerivedDaily.calendar_date >= start,
        DerivedDaily.calendar_date <= end,
    )
    rows = (await session.execute(statement)).all()
    return Gold(
        readings={
            (metric, day): Reading(value=value, coverage=coverage)
            for metric, day, value, coverage in rows
        }
    )


async def _write(session: AsyncSession, *, user_id: uuid.UUID, days: Sequence[DayScore]) -> None:
    score_rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "calendar_date": day.calendar_date,
            "score": day.score,
            "coverage": day.coverage,
            "trusted": day.trusted,
        }
        for day in days
    ]
    for group in chunked(score_rows):
        statement = pg_insert(VitalsScore).values(group)
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_vitals_score_day",
                set_={
                    "score": statement.excluded.score,
                    "coverage": statement.excluded.coverage,
                    "trusted": statement.excluded.trusted,
                    "computed_at": func.now(),
                },
            )
        )

    pillar_rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "calendar_date": day.calendar_date,
            "pillar": pillar.name,
            "score": pillar.score,
            "coverage": pillar.coverage,
            "weight": pillar.weight,
        }
        for day in days
        for pillar in day.pillars
    ]
    for group in chunked(pillar_rows):
        statement = pg_insert(ScorePillar).values(group)
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_score_pillar_day",
                set_={
                    "score": statement.excluded.score,
                    "coverage": statement.excluded.coverage,
                    "weight": statement.excluded.weight,
                },
            )
        )

    # Contributions are deleted and rewritten rather than upserted: a recalibration can
    # *remove* a line, and an upsert would leave the old one behind, silently breaking
    # the one property the waterfall promises — that the effects sum to the score.
    await session.execute(
        delete(ScoreContribution).where(
            ScoreContribution.user_id == user_id,
            ScoreContribution.calendar_date.in_([day.calendar_date for day in days]),
        )
    )
    contribution_rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "calendar_date": day.calendar_date,
            "pillar": contribution.pillar,
            "metric": contribution.metric,
            "value": contribution.value,
            "points": contribution.points,
            "weight": contribution.weight,
            "coverage": contribution.coverage,
            "effect": contribution.effect,
            "headroom": contribution.headroom,
        }
        for day in days
        for contribution in day.contributions
    ]
    for group in chunked(contribution_rows):
        await session.execute(pg_insert(ScoreContribution).values(group))
