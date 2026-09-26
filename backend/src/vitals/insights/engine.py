"""Running the analysis over stored data and writing what it found.

Loads the tags and the series, hands them to `analysis`, and stores the result. The
statistics live next door and know nothing about databases; this knows nothing about
statistics.

The metrics it tests are a deliberately short list. Every extra metric is another
column in the multiple-comparisons denominator, so adding one makes every *other*
finding harder to reach — which is the right trade only for metrics a tag could
plausibly move. Throwing all fifty-five at it would bury the real effects under their
own correction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as gold
from vitals.context import store as context_store
from vitals.db.models import DerivedDaily, Insight, MetricDaily
from vitals.insights.analysis import Finding, analyse
from vitals.logging import get_logger
from vitals.normalize import canonical as silver

log = get_logger(__name__)

# How far back to look. Long enough for a year of seasonality, short enough that a
# habit you dropped two years ago is not still being tested.
WINDOW_DAYS = 400
# Below this there is nothing to say, and saying it anyway trains people to ignore
# the screen.
MIN_TAGGED_DAYS = 8

# What a day's context could plausibly move, from silver (what the device saw) and
# gold (what it meant). Short on purpose — see the module docstring.
SILVER_METRICS: tuple[str, ...] = (
    silver.HRV_OVERNIGHT_AVG,
    silver.RESTING_HR,
    silver.SLEEP_DURATION,
    silver.SLEEP_SCORE,
    silver.SLEEP_DEEP,
    silver.SLEEP_REM,
    silver.STRESS_AVG,
    silver.BODY_BATTERY_HIGH,
    silver.STEPS,
)
GOLD_METRICS: tuple[str, ...] = (
    gold.HRV_DEVIATION,
    gold.RHR_DEVIATION,
    gold.SLEEP_EFFICIENCY,
)


@dataclass
class RefreshResult:
    tested: int = 0
    found: int = 0
    tagged_days: int = 0
    window_start: date | None = None
    window_end: date | None = None
    skipped: str | None = None


async def _series(
    session: AsyncSession, *, user_id: uuid.UUID, start: date, end: date
) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}

    silver_rows = (
        await session.execute(
            select(MetricDaily.metric, MetricDaily.calendar_date, MetricDaily.value).where(
                MetricDaily.user_id == user_id,
                MetricDaily.metric.in_(SILVER_METRICS),
                MetricDaily.calendar_date >= start,
                MetricDaily.calendar_date <= end,
            )
        )
    ).all()
    for metric, day, value in silver_rows:
        out.setdefault(metric, {})[day] = value

    gold_rows = (
        await session.execute(
            select(DerivedDaily.metric, DerivedDaily.calendar_date, DerivedDaily.value).where(
                DerivedDaily.user_id == user_id,
                DerivedDaily.metric.in_(GOLD_METRICS),
                DerivedDaily.calendar_date >= start,
                DerivedDaily.calendar_date <= end,
            )
        )
    ).all()
    for metric, day, value in gold_rows:
        out.setdefault(metric, {})[day] = value

    return out


async def refresh(
    session: AsyncSession, *, user_id: uuid.UUID, today: date | None = None
) -> RefreshResult:
    """Re-run the analysis and replace what was stored."""
    end = today or datetime.now(UTC).date()
    start = end - timedelta(days=WINDOW_DAYS)

    tags = await context_store.span(session, user_id=user_id, start=start, end=end)
    if len(tags) < MIN_TAGGED_DAYS:
        # Not a failure. There is genuinely nothing to say yet, and inventing
        # something would train people to ignore the screen.
        return RefreshResult(
            tagged_days=len(tags),
            window_start=start,
            window_end=end,
            skipped=f"only {len(tags)} tagged day(s); needs {MIN_TAGGED_DAYS}",
        )

    tagged: dict[str, set[date]] = {}
    for day, names in tags.items():
        for name in names:
            tagged.setdefault(name, set()).add(day)

    series = await _series(session, user_id=user_id, start=start, end=end)
    if not series:
        return RefreshResult(
            tagged_days=len(tags),
            window_start=start,
            window_end=end,
            skipped="no metrics in the window to test against",
        )

    findings = analyse(tagged=tagged, series=series)
    await _write(session, user_id=user_id, findings=findings, start=start, end=end)

    result = RefreshResult(
        tested=len(findings),
        found=sum(1 for f in findings if f.significant),
        tagged_days=len(tags),
        window_start=start,
        window_end=end,
    )
    log.info(
        "insights.refreshed",
        tested=result.tested,
        found=result.found,
        tagged_days=result.tagged_days,
    )
    return result


async def _write(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    findings: list[Finding],
    start: date,
    end: date,
) -> None:
    """Delete and rewrite, rather than upsert.

    A finding that no longer holds has to disappear. An upsert would leave last
    month's conclusion on screen for a pair the latest run did not even report on,
    which is the one failure mode that would make this actively misleading.
    """
    await session.execute(delete(Insight).where(Insight.user_id == user_id))

    if findings:
        await session.execute(
            pg_insert(Insight).values(
                [
                    {
                        "id": uuid.uuid4(),
                        "user_id": user_id,
                        "tag": f.tag,
                        "metric": f.metric,
                        "lag": f.lag,
                        "n_with": f.n_with,
                        "n_without": f.n_without,
                        "mean_with": f.mean_with,
                        "mean_without": f.mean_without,
                        "delta": f.delta,
                        "effect": f.effect,
                        "p_value": f.p_value,
                        "significant": f.significant,
                        "tested": len(findings),
                        "window_start": start,
                        "window_end": end,
                    }
                    for f in findings
                ]
            )
        )
    await session.commit()
