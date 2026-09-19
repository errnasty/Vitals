"""Bulk inserts, against the limit that only shows up on real data.

Postgres allows 32767 bind parameters in one statement, and a multi-row INSERT spends
one per column per row. A week of test data never comes close; a single day of Garmin
stress samples is several hundred rows, and a backfill is hundreds of thousands. This
is the seam where that difference used to become a production-only failure.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.bulk import MAX_BIND_PARAMS, chunked
from vitals.db.models import AppUser, MetricSample
from vitals.ingest.raw_store import RawRecord, RawStore
from vitals.normalize import canonical as silver
from vitals.normalize import normalize

DAY = date(2026, 8, 21)


def test_nothing_in_nothing_out() -> None:
    assert list(chunked([])) == []


def test_rows_survive_the_split_intact() -> None:
    rows = [{"a": i, "b": i} for i in range(100)]

    assert [row for group in chunked(rows) for row in group] == rows


def test_no_group_can_exceed_the_parameter_ceiling() -> None:
    wide = [dict.fromkeys(f"c{i}" for i in range(20)) for _ in range(5000)]

    for group in chunked(wide):
        assert len(group) * 20 <= MAX_BIND_PARAMS


def test_a_wider_row_means_fewer_rows_per_statement() -> None:
    narrow = next(chunked([{"a": 1} for _ in range(100_000)]))
    wide = next(chunked([dict.fromkeys(f"c{i}" for i in range(50)) for _ in range(100_000)]))

    assert len(narrow) > len(wide)


async def test_a_day_of_intraday_samples_normalizes_without_blowing_the_limit(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Garmin samples stress every three minutes; a page of those days is ~240k rows."""
    store = RawStore(pg_session, user_id=pg_user.id, source="garmin")
    records = []
    for offset in range(8):
        day = DAY - timedelta(days=offset)
        base = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)
        records.append(
            RawRecord(
                "all_day_stress",
                {
                    "calendarDate": day.isoformat(),
                    "avgStressLevel": 30,
                    "stressValuesArray": [
                        [base + minute * 60_000, 20 + minute % 40] for minute in range(600)
                    ],
                },
                calendar_date=day,
            )
        )
    await store.store(records)

    result = await normalize(pg_session, user_id=pg_user.id)

    stored = await pg_session.scalar(
        select(func.count()).select_from(MetricSample).where(MetricSample.metric == silver.STRESS)
    )
    assert result.samples == 4800
    assert stored == 4800
