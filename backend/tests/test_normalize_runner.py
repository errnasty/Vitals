"""Bronze → silver, against a real Postgres.

Everything here is a property of the upsert and the ordering, so SQLite would be
testing a different program: DISTINCT ON, ON CONFLICT and the keyset cursor are the
mechanics under test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import Activity, AppUser, MetricDaily, MetricSample, SleepSession
from vitals.ingest.raw_store import RawRecord, RawStore
from vitals.normalize import available_metrics, daily_series, normalize
from vitals.normalize import canonical as c

DAY = date(2026, 8, 21)
NEXT = date(2026, 8, 22)
NOON_MS = int(datetime(2026, 8, 21, 6, 0, tzinfo=UTC).timestamp() * 1000)


def _store(session: AsyncSession, user: AppUser) -> RawStore:
    return RawStore(session, user_id=user.id, source="garmin")


async def _value(session: AsyncSession, user: AppUser, metric: str, day: date = DAY):
    return await session.scalar(
        select(MetricDaily.value).where(
            MetricDaily.user_id == user.id,
            MetricDaily.metric == metric,
            MetricDaily.calendar_date == day,
        )
    )


async def _count(session: AsyncSession, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_a_payload_becomes_silver_rows(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _store(pg_session, pg_user).store(
        [RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY)]
    )

    result = await normalize(pg_session, user_id=pg_user.id)

    assert result.payloads == 1
    assert result.daily == 1
    assert await _value(pg_session, pg_user, c.RESTING_HR) == 48


async def test_normalizing_twice_changes_nothing(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Silver is a projection of bronze, not an accumulation on top of it."""
    await _store(pg_session, pg_user).store(
        [
            RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY),
            RawRecord(
                "all_day_stress",
                {
                    "calendarDate": "2026-08-21",
                    "avgStressLevel": 31,
                    "stressValuesArray": [[NOON_MS, 22], [NOON_MS + 180_000, 44]],
                },
                calendar_date=DAY,
            ),
        ]
    )

    await normalize(pg_session, user_id=pg_user.id)
    daily_after_first = await _count(pg_session, MetricDaily)
    samples_after_first = await _count(pg_session, MetricSample)

    await normalize(pg_session, user_id=pg_user.id)

    assert await _count(pg_session, MetricDaily) == daily_after_first
    assert await _count(pg_session, MetricSample) == samples_after_first


async def test_the_higher_priority_endpoint_wins(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Both endpoints report a resting heart rate; the daily summary is the better source."""
    await _store(pg_session, pg_user).store(
        [
            RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY),
            RawRecord(
                "user_summary",
                {"calendarDate": "2026-08-21", "restingHeartRate": 52},
                calendar_date=DAY,
            ),
        ]
    )

    await normalize(pg_session, user_id=pg_user.id)

    assert await _value(pg_session, pg_user, c.RESTING_HR) == 52


async def test_a_revised_day_overwrites_the_original(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Garmin revises days retroactively; bronze keeps both and silver holds the newer."""
    store = _store(pg_session, pg_user)
    await store.store(
        [RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY)]
    )
    await store.store(
        [RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 51}, calendar_date=DAY)]
    )

    await normalize(pg_session, user_id=pg_user.id)

    assert await store.count() == 2  # both versions still in bronze
    assert await _value(pg_session, pg_user, c.RESTING_HR) == 51


async def test_recompute_after_a_fix_changes_the_value_in_place(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """The reason bronze exists: a wrong number is a recompute, not a data loss."""
    await _store(pg_session, pg_user).store(
        [RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY)]
    )
    await normalize(pg_session, user_id=pg_user.id)

    await pg_session.execute(
        MetricDaily.__table__.update().where(MetricDaily.metric == c.RESTING_HR).values(value=999)
    )
    await pg_session.commit()

    await normalize(pg_session, user_id=pg_user.id)

    assert await _value(pg_session, pg_user, c.RESTING_HR) == 48


async def test_sleep_and_activities_land_in_their_own_tables(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _store(pg_session, pg_user).store(
        [
            RawRecord(
                "sleep_detail",
                {
                    "dailySleepDTO": {
                        "calendarDate": "2026-08-21",
                        "sleepTimeSeconds": 27000,
                        "deepSleepSeconds": 5400,
                        "sleepScores": {"overall": {"value": 82}},
                    }
                },
                calendar_date=DAY,
            ),
            RawRecord(
                "activity",
                {
                    "activityId": 987654321,
                    "activityName": "Morning Run",
                    "activityType": {"typeKey": "running"},
                    "startTimeGMT": "2026-08-21 06:00:00",
                    "distance": 10200.0,
                },
                entity_key="987654321",
            ),
        ]
    )

    result = await normalize(pg_session, user_id=pg_user.id)

    assert (result.sleep, result.activities) == (1, 1)
    night = await pg_session.scalar(select(SleepSession))
    assert night is not None and night.duration_s == 27000 and night.score == 82
    activity = await pg_session.scalar(select(Activity))
    assert activity is not None and activity.external_id == "987654321"
    # The headline sleep numbers are mirrored into metric_daily too.
    assert await _value(pg_session, pg_user, c.SLEEP_DURATION) == 27000


async def test_an_undated_payload_survives_a_windowed_run(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Activities carry no calendar date; a naive BETWEEN would silently drop every one."""
    await _store(pg_session, pg_user).store(
        [
            RawRecord(
                "activity",
                {"activityId": 1, "activityType": {"typeKey": "running"}, "distance": 5000.0},
                entity_key="1",
            )
        ]
    )

    result = await normalize(pg_session, user_id=pg_user.id, start=DAY, end=NEXT)

    assert result.activities == 1


async def test_the_window_excludes_days_outside_it(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _store(pg_session, pg_user).store(
        [
            RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY),
            RawRecord("rhr_daily", {"calendarDate": "2026-08-22", "value": 50}, calendar_date=NEXT),
        ]
    )

    await normalize(pg_session, user_id=pg_user.id, start=NEXT, end=NEXT)

    assert await _value(pg_session, pg_user, c.RESTING_HR, DAY) is None
    assert await _value(pg_session, pg_user, c.RESTING_HR, NEXT) == 50


async def test_a_dry_run_writes_nothing(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await _store(pg_session, pg_user).store(
        [RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY)]
    )

    result = await normalize(pg_session, user_id=pg_user.id, dry_run=True)

    assert result.payloads == 1
    assert result.coverage[0].rows == 1
    assert await _count(pg_session, MetricDaily) == 0


async def test_coverage_counts_payloads_that_produced_nothing(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """The number that tells you a normalizer has met a shape it was not written for."""
    await _store(pg_session, pg_user).store(
        [
            RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY),
            RawRecord(
                "rhr_daily", {"calendarDate": "2026-08-22", "surprise": 1}, calendar_date=NEXT
            ),
        ]
    )

    result = await normalize(pg_session, user_id=pg_user.id)
    coverage = {item.endpoint: item for item in result.coverage}

    assert coverage["rhr_daily"].payloads == 2
    assert coverage["rhr_daily"].barren == 1
    assert coverage["rhr_daily"].ok is False


async def test_an_endpoint_with_no_normalizer_is_reported_not_ignored(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _store(pg_session, pg_user).store(
        [RawRecord("weekly_stress", {"calendarDate": "2026-08-21", "value": 30}, calendar_date=DAY)]
    )

    result = await normalize(pg_session, user_id=pg_user.id)

    assert result.unmapped == ["weekly_stress"]


async def test_selecting_endpoints_limits_the_run(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _store(pg_session, pg_user).store(
        [
            RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY),
            RawRecord(
                "daily_steps",
                {"calendarDate": "2026-08-21", "totalSteps": 9000},
                calendar_date=DAY,
            ),
        ]
    )

    await normalize(pg_session, user_id=pg_user.id, endpoints=["daily_steps"])

    assert await _value(pg_session, pg_user, c.RESTING_HR) is None
    assert await _value(pg_session, pg_user, c.STEPS) == 9000


async def test_paging_covers_more_rows_than_one_page(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """The keyset cursor is what keeps a seven-year recompute inside a page of memory."""
    from vitals.normalize import runner

    days = [date(2026, 1, 1).toordinal() + offset for offset in range(25)]
    await _store(pg_session, pg_user).store(
        [
            RawRecord(
                "rhr_daily",
                {"calendarDate": date.fromordinal(day).isoformat(), "value": 40 + index},
                calendar_date=date.fromordinal(day),
            )
            for index, day in enumerate(days)
        ]
    )

    original, runner.PAGE_SIZE = runner.PAGE_SIZE, 10
    try:
        result = await normalize(pg_session, user_id=pg_user.id)
    finally:
        runner.PAGE_SIZE = original

    assert result.payloads == 25
    assert await _count(pg_session, MetricDaily) == 25


async def test_the_resolver_prefers_the_better_source(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Two devices, one day: the watch wins, and the phone fills the day it missed."""
    pg_session.add_all(
        [
            MetricDaily(
                user_id=pg_user.id,
                metric=c.STEPS,
                calendar_date=DAY,
                source="garmin",
                value=12000,
                unit="count",
            ),
            MetricDaily(
                user_id=pg_user.id,
                metric=c.STEPS,
                calendar_date=DAY,
                source="healthkit",
                value=11000,
                unit="count",
            ),
            MetricDaily(
                user_id=pg_user.id,
                metric=c.STEPS,
                calendar_date=NEXT,
                source="healthkit",
                value=8000,
                unit="count",
            ),
        ]
    )
    await pg_session.commit()

    series = await daily_series(pg_session, user_id=pg_user.id, metric=c.STEPS)

    assert [(p.calendar_date, p.value, p.source) for p in series] == [
        (DAY, 12000.0, "garmin"),
        (NEXT, 8000.0, "healthkit"),
    ]


async def test_the_inventory_reports_what_can_be_computed(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    await _store(pg_session, pg_user).store(
        [
            RawRecord("rhr_daily", {"calendarDate": "2026-08-21", "value": 48}, calendar_date=DAY),
            RawRecord("rhr_daily", {"calendarDate": "2026-08-22", "value": 50}, calendar_date=NEXT),
        ]
    )
    await normalize(pg_session, user_id=pg_user.id)

    inventory = await available_metrics(pg_session, user_id=pg_user.id)

    assert inventory[c.RESTING_HR] == (DAY, NEXT, 2)
