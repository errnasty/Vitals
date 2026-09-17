"""Running every analytics module over a window and writing the result to gold.

Same contract as the silver runner, for the same reason: every write is an upsert on
`(user, metric, day)`, so a recompute is idempotent and gold is disposable. Drop the
table, run it again, get the same numbers. Nothing in this layer is the only copy of
anything.

The engine's own job is small — decide the window, load once, walk the days, turn each
module's `inputs` count into a coverage fraction, and upsert. All the domain reasoning
lives in the five modules, which are pure and know nothing about databases.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import body, longevity, recovery, sleep, training
from vitals.analytics import canonical as d
from vitals.analytics.model import Derived, Module
from vitals.analytics.series import MAX_WINDOW_DAYS, Inputs, load_inputs
from vitals.analytics.training import CTL_WARMUP_DAYS
from vitals.db.bulk import chunked
from vitals.db.models import DerivedDaily, MetricDaily
from vitals.logging import get_logger
from vitals.normalize import canonical as silver
from vitals.normalize.resolver import DEFAULT_PREFERENCE

log = get_logger(__name__)

BATCH_DAYS = 90

# Enough history for every metric: the longest declared window, or the run-up an
# exponentially weighted average needs to forget its seed — whichever is larger.
LOOKBACK_DAYS = max(MAX_WINDOW_DAYS, CTL_WARMUP_DAYS)

MODULES: tuple[tuple[str, Module], ...] = (
    ("training", training.compute),
    ("recovery", recovery.compute),
    ("sleep", sleep.compute),
    ("body", body.compute),
    ("longevity", longevity.compute),
)

# Every silver metric the modules read. Loaded once per run.
SOURCE_METRICS: tuple[str, ...] = (
    silver.STEPS,
    silver.RESTING_HR,
    silver.HRV_OVERNIGHT_AVG,
    silver.SLEEP_DURATION,
    silver.WEIGHT,
    silver.BODY_FAT_PCT,
    silver.VO2MAX_RUNNING,
    silver.INTENSITY_MINUTES_MODERATE,
    silver.INTENSITY_MINUTES_VIGOROUS,
)


@dataclass
class RecomputeResult:
    start: date | None = None
    end: date | None = None
    days: int = 0
    rows: int = 0
    # metric -> (rows written, mean coverage)
    metrics: dict[str, tuple[int, float]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.days == 0


async def silver_span(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[date | None, date | None]:
    """The days silver actually covers — the honest default window."""
    row = (
        await session.execute(
            select(func.min(MetricDaily.calendar_date), func.max(MetricDaily.calendar_date)).where(
                MetricDaily.user_id == user_id
            )
        )
    ).one()
    return row[0], row[1]


async def recompute(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    prefer: Sequence[str] = DEFAULT_PREFERENCE,
    dry_run: bool = False,
) -> RecomputeResult:
    """Rebuild gold for one user and window."""
    first, last = await silver_span(session, user_id=user_id)
    if first is None or last is None:
        return RecomputeResult()

    window_start = max(start, first) if start else first
    window_end = min(end, last) if end else last
    if window_start > window_end:
        return RecomputeResult()

    result = RecomputeResult(start=window_start, end=window_end)
    totals: dict[str, list[float]] = {}

    # Chunked so the loaded history stays bounded on a multi-year recompute; each
    # chunk still reaches back far enough to be correct on its own first day.
    chunk_start = window_start
    while chunk_start <= window_end:
        chunk_end = min(chunk_start + timedelta(days=BATCH_DAYS - 1), window_end)
        inputs = await load_inputs(
            session,
            user_id=user_id,
            metrics=SOURCE_METRICS,
            start=chunk_start,
            end=chunk_end,
            prefer=prefer,
            lookback_days=LOOKBACK_DAYS,
        )
        rows = _derive(inputs)
        result.days += len(inputs.days())
        result.rows += len(rows)
        for row in rows:
            totals.setdefault(row.metric, []).append(_coverage(row))
        if rows and not dry_run:
            await _write(session, user_id=user_id, rows=rows)
        chunk_start = chunk_end + timedelta(days=1)

    result.metrics = {
        metric: (len(values), sum(values) / len(values)) for metric, values in totals.items()
    }

    if not dry_run:
        await session.commit()

    log.info(
        "analytics.finished",
        days=result.days,
        rows=result.rows,
        metrics=len(result.metrics),
        dry_run=dry_run,
    )
    return result


def _derive(inputs: Inputs) -> list[Derived]:
    out: list[Derived] = []
    for name, module in MODULES:
        for day in inputs.days():
            try:
                out.extend(module(inputs, day))
            except Exception as exc:  # noqa: BLE001 - one module must not sink the run
                log.error(
                    "analytics.module_failed",
                    module=name,
                    day=day.isoformat(),
                    error=f"{type(exc).__name__}: {exc}",
                )
    return out


def _coverage(row: Derived) -> float:
    """Observations behind the value, over the window it claims to summarise."""
    window = d.window_for(row.metric)
    if window <= 0:
        return 1.0
    return min(1.0, row.inputs / window)


async def _write(session: AsyncSession, *, user_id: uuid.UUID, rows: Sequence[Derived]) -> None:
    payload = {}
    for row in rows:
        payload[(row.metric, row.calendar_date)] = {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "metric": row.metric,
            "calendar_date": row.calendar_date,
            "value": row.value,
            "unit": d.unit_for(row.metric),
            "coverage": _coverage(row),
            "inputs": row.inputs,
        }
    if not payload:
        return

    for group in chunked(list(payload.values())):
        statement = pg_insert(DerivedDaily).values(group)
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_derived_daily_point",
                set_={
                    "value": statement.excluded.value,
                    "unit": statement.excluded.unit,
                    "coverage": statement.excluded.coverage,
                    "inputs": statement.excluded.inputs,
                    "computed_at": func.now(),
                },
            )
        )
