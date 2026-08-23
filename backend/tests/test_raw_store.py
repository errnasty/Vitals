"""Bronze, against a real Postgres.

The content-hash dedup is the reason a trailing window can be re-fetched every few
hours for years without the table growing, and the reason Garmin's retroactive
revisions turn into a free version history. Both are properties of JSONB, ON CONFLICT
and NULLS NOT DISTINCT, so they are tested against the real database.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import AppUser, RawPayload
from vitals.ingest.raw_store import RawRecord, RawStore, payload_hash

DAY = date(2026, 8, 21)


def _store(session: AsyncSession, user: AppUser) -> RawStore:
    return RawStore(session, user_id=user.id, source="garmin")


async def test_a_payload_is_stored_once(pg_session: AsyncSession, pg_user: AppUser) -> None:
    store = _store(pg_session, pg_user)
    record = RawRecord(
        "sleep_daily", {"calendarDate": "2026-08-21", "score": 82}, calendar_date=DAY
    )

    first = await store.store([record])
    second = await store.store([record])

    assert (first.stored, first.unchanged) == (1, 0)
    assert (second.stored, second.unchanged) == (0, 1)
    assert await store.count() == 1


async def test_re_fetching_an_unchanged_window_is_free(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """A week re-fetched every few hours must not grow the table."""
    store = _store(pg_session, pg_user)
    week = [
        RawRecord(
            "rhr_daily",
            {"calendarDate": f"2026-08-{day}", "value": 48},
            calendar_date=date(2026, 8, day),
        )
        for day in range(15, 22)
    ]

    await store.store(week)
    for _ in range(5):
        result = await store.store(week)
        assert result.stored == 0

    assert await store.count() == 7


async def test_a_revision_is_kept_beside_the_original(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Garmin recomputes sleep scores days later; both versions are worth having."""
    store = _store(pg_session, pg_user)

    await store.store([RawRecord("sleep_daily", {"score": 82}, calendar_date=DAY)])
    await store.store([RawRecord("sleep_daily", {"score": 79}, calendar_date=DAY)])

    rows = (
        (
            await pg_session.execute(
                select(RawPayload)
                .where(RawPayload.endpoint == "sleep_daily")
                .order_by(RawPayload.first_seen_at)
            )
        )
        .scalars()
        .all()
    )

    assert [row.payload["score"] for row in rows] == [82, 79]
    assert len({row.payload_hash for row in rows}) == 2


async def test_seeing_a_payload_again_updates_last_seen(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    store = _store(pg_session, pg_user)
    record = RawRecord("training_status", {"status": "productive"}, calendar_date=DAY)

    await store.store([record])
    row = (await pg_session.execute(select(RawPayload))).scalar_one()
    first_seen, last_seen = row.first_seen_at, row.last_seen_at

    await store.store([record])
    await pg_session.refresh(row)

    assert row.first_seen_at == first_seen
    assert row.last_seen_at > last_seen


async def test_undated_payloads_deduplicate_too(pg_session: AsyncSession, pg_user: AppUser) -> None:
    """NULL calendar_date must still collide, which needs NULLS NOT DISTINCT."""
    store = _store(pg_session, pg_user)
    record = RawRecord("race_predictions", {"time5K": 1234})

    await store.store([record])
    await store.store([record])

    assert await store.count() == 1


async def test_the_same_day_from_two_endpoints_is_two_rows(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    store = _store(pg_session, pg_user)

    await store.store(
        [
            RawRecord("sleep_daily", {"score": 82}, calendar_date=DAY),
            RawRecord("sleep_detail", {"score": 82}, calendar_date=DAY),
        ]
    )

    assert await store.count() == 2


async def test_duplicates_inside_one_batch_are_collapsed(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Postgres refuses to touch a row twice in one statement; the batch must not."""
    store = _store(pg_session, pg_user)
    record = RawRecord("body_battery", {"charged": 71}, calendar_date=DAY)

    result = await store.store([record, record, record])

    assert result.stored == 1
    assert await store.count() == 1


async def test_activities_are_keyed_by_id(pg_session: AsyncSession, pg_user: AppUser) -> None:
    store = _store(pg_session, pg_user)

    await store.store(
        [
            RawRecord("activity", {"activityId": 1}, calendar_date=DAY, entity_key="1"),
            RawRecord("activity", {"activityId": 2}, calendar_date=DAY, entity_key="2"),
        ]
    )

    assert await store.known_entity_keys("activity") == {"1", "2"}
    assert await store.count("activity") == 2


async def test_date_range_reports_what_landed(pg_session: AsyncSession, pg_user: AppUser) -> None:
    store = _store(pg_session, pg_user)
    await store.store(
        [
            RawRecord("rhr_daily", {"v": 1}, calendar_date=date(2019, 1, 1)),
            RawRecord("rhr_daily", {"v": 2}, calendar_date=date(2026, 8, 23)),
        ]
    )

    assert await store.date_range() == (date(2019, 1, 1), date(2026, 8, 23))


async def test_one_users_data_is_invisible_to_another(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Multi-user-ready from day one: every query is scoped by user."""
    other = AppUser(id=uuid.uuid4(), email="someone@example.com")
    pg_session.add(other)
    await pg_session.commit()

    await _store(pg_session, pg_user).store([RawRecord("rhr_daily", {"v": 1}, calendar_date=DAY)])

    assert await RawStore(pg_session, user_id=other.id, source="garmin").count() == 0


def test_hashing_ignores_key_order() -> None:
    """A provider reordering its JSON keys is not a revision."""
    assert payload_hash({"a": 1, "b": 2}) == payload_hash({"b": 2, "a": 1})
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})
