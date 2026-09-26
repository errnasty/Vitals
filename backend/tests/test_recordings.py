"""Storing a recording once, and turning it into silver.

The two properties worth pinning down: a re-download of an unchanged file writes no
bytes, and a decode that fails keeps the file rather than discarding it. Both are
about a resource that cost a rate-governed request to obtain and cannot be obtained
again if the unofficial API goes away.
"""

from __future__ import annotations

import gzip
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fit_fixture import build
from tests.support import EMAIL, USER_ID
from vitals.db.models import Activity, ActivityDetail, AppUser, RawFile
from vitals.ingest import files
from vitals.normalize import recordings

SOURCE = "garmin"


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


def _fit(count: int = 200) -> bytes:
    return build(
        [
            {
                "lat": 51.5 + i * 1e-5,
                "lon": -0.12 + i * 1e-5,
                "alt": 10.0 + i * 0.1,
                "hr": 140,
                "cad": 85,
                "dist": i * 3.0,
                "speed": 3.0,
                "power": 200,
            }
            for i in range(count)
        ]
    )


async def _activity(session: AsyncSession, external_id: str) -> Activity:
    row = Activity(
        user_id=USER_ID,
        source=SOURCE,
        external_id=external_id,
        activity_type="running",
        started_at=datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
        duration_s=3600.0,
    )
    session.add(row)
    await session.commit()
    return row


async def _daily_metric(session: AsyncSession) -> None:
    from vitals.db.models import MetricDaily
    from vitals.normalize import canonical as silver

    session.add(
        MetricDaily(
            user_id=USER_ID,
            metric=silver.RESTING_HR,
            calendar_date=datetime(2026, 9, 1, tzinfo=UTC).date(),
            source=SOURCE,
            value=54.0,
            unit=silver.unit_for(silver.RESTING_HR),
        )
    )
    await session.commit()


async def test_a_file_is_stored_compressed_with_its_real_size_recorded(
    pg_session: AsyncSession, user: AppUser
) -> None:
    blob = _fit()

    stored = await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=blob
    )

    assert stored.fresh
    assert stored.original_bytes == len(blob)
    row = await pg_session.get(RawFile, stored.file_id)
    assert row is not None
    assert gzip.decompress(row.content) == blob


async def test_downloading_the_same_recording_again_writes_no_bytes(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The property that makes a trailing re-fetch affordable."""
    blob = _fit()

    first = await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=blob
    )
    before = (await pg_session.get(RawFile, first.file_id)).last_seen_at  # type: ignore[union-attr]

    second = await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=blob
    )

    assert second.file_id == first.file_id
    assert not second.fresh
    count = await pg_session.scalar(select(RawFile.id).where(RawFile.user_id == USER_ID))
    assert count == first.file_id
    after = (await pg_session.get(RawFile, first.file_id)).last_seen_at  # type: ignore[union-attr]
    assert after >= before


async def test_a_changed_recording_replaces_rather_than_accumulates(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A FIT file is not revised the way a JSON summary is, so history buys nothing."""
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=_fit(50)
    )
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=_fit(80)
    )

    rows = (
        (await pg_session.execute(select(RawFile).where(RawFile.user_id == USER_ID)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert len(gzip.decompress(rows[0].content)) == len(_fit(80))


async def test_known_keys_is_what_stops_the_sync_re_downloading(
    pg_session: AsyncSession, user: AppUser
) -> None:
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="7", content=_fit(10)
    )

    known = await files.known_keys(pg_session, user_id=USER_ID, source=SOURCE, kind="fit")

    assert known == {"7"}


# ── bronze -> silver ────────────────────────────────────────────────────────────


async def test_a_stored_recording_becomes_activity_detail(
    pg_session: AsyncSession, user: AppUser
) -> None:
    activity = await _activity(pg_session, "1")
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=_fit()
    )

    result = await recordings.rebuild(pg_session, user_id=USER_ID)

    assert result.parsed == 1
    detail = await pg_session.scalar(
        select(ActivityDetail).where(ActivityDetail.user_id == USER_ID)
    )
    assert detail is not None
    assert detail.activity_id == activity.id
    assert detail.samples == 200
    assert detail.sample_interval_s == 1.0
    assert detail.route_path is not None


async def test_rebuilding_twice_does_not_duplicate(pg_session: AsyncSession, user: AppUser) -> None:
    await _activity(pg_session, "1")
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=_fit()
    )

    await recordings.rebuild(pg_session, user_id=USER_ID)
    second = await recordings.rebuild(pg_session, user_id=USER_ID)

    assert second.parsed == 0
    assert second.skipped == 1
    rows = (
        (await pg_session.execute(select(ActivityDetail).where(ActivityDetail.user_id == USER_ID)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_force_re_decodes_everything(pg_session: AsyncSession, user: AppUser) -> None:
    """What a change to the reductions needs, and the reason the file is kept at all."""
    await _activity(pg_session, "1")
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=_fit()
    )
    await recordings.rebuild(pg_session, user_id=USER_ID)

    again = await recordings.rebuild(pg_session, user_id=USER_ID, force=True)

    assert again.parsed == 1
    assert again.skipped == 0


async def test_an_unreadable_file_is_counted_and_kept(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A decoder that cannot read it today is not a reason to throw away a request."""
    await _activity(pg_session, "1")
    await files.put(
        pg_session,
        user_id=USER_ID,
        source=SOURCE,
        kind="fit",
        entity_key="1",
        content=b"not a recording at all",
    )

    result = await recordings.rebuild(pg_session, user_id=USER_ID)

    assert result.unreadable == 1
    assert result.parsed == 0
    assert await pg_session.scalar(select(RawFile.id).where(RawFile.user_id == USER_ID)) is not None


async def test_a_recording_whose_activity_is_not_normalized_yet_waits(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A detail row pointing at no activity is worse than no detail row."""
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="99", content=_fit()
    )

    result = await recordings.rebuild(pg_session, user_id=USER_ID)

    assert result.orphaned == 1
    assert result.parsed == 0


async def test_another_user_s_recordings_are_never_touched(
    pg_session: AsyncSession, user: AppUser
) -> None:
    other = uuid.uuid4()
    pg_session.add(AppUser(id=other, email="other@example.com"))
    await pg_session.commit()
    await files.put(
        pg_session, user_id=other, source=SOURCE, kind="fit", entity_key="1", content=_fit()
    )

    result = await recordings.rebuild(pg_session, user_id=USER_ID)

    assert result.files == 0


async def test_the_recording_reaches_gold(pg_session: AsyncSession, user: AppUser) -> None:
    """Otherwise `activity_detail` is a table nothing reads.

    A decoupling and a climb from the FIT file have to come out the far end as
    derived metrics, or the whole download was storage for its own sake.
    """
    from vitals.analytics import canonical as gold
    from vitals.analytics import recompute
    from vitals.db.models import DerivedDaily

    await _activity(pg_session, "1")
    # The gold layer's window comes from the daily metrics, so a day needs one to
    # exist at all. That is the right behaviour — an activity is not a day — but it
    # means this test has to put one there.
    await _daily_metric(pg_session)
    # Heart rate drifting against a held speed, over a steady climb.
    blob = build(
        [
            {
                "lat": 51.5 + i * 1e-5,
                "lon": -0.12,
                "alt": 10.0 + i * 0.5,
                "hr": 140 if i < 200 else 165,
                "cad": 85,
                "dist": i * 3.0,
                "speed": 3.0,
                "power": 200,
            }
            for i in range(400)
        ]
    )
    await files.put(
        pg_session, user_id=USER_ID, source=SOURCE, kind="fit", entity_key="1", content=blob
    )
    await recordings.rebuild(pg_session, user_id=USER_ID)

    await recompute(pg_session, user_id=USER_ID, start=datetime(2026, 9, 1, tzinfo=UTC).date())

    rows = {
        metric: value
        for metric, value in (
            await pg_session.execute(
                select(DerivedDaily.metric, DerivedDaily.value).where(
                    DerivedDaily.user_id == USER_ID,
                    DerivedDaily.metric.in_([gold.DECOUPLING, gold.ASCENT]),
                )
            )
        ).all()
    }

    assert rows[gold.DECOUPLING] > 10.0, "the second half cost more heartbeats"
    assert rows[gold.ASCENT] == pytest.approx(199.5, abs=1.0)


async def test_a_day_with_no_recording_has_no_ascent_rather_than_zero(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """Zero would flatten every mountain week for anyone whose history predates this."""
    from vitals.analytics import canonical as gold
    from vitals.analytics import recompute
    from vitals.db.models import DerivedDaily

    await _activity(pg_session, "1")
    await _daily_metric(pg_session)

    await recompute(pg_session, user_id=USER_ID, start=datetime(2026, 9, 1, tzinfo=UTC).date())

    found = await pg_session.scalar(
        select(DerivedDaily.value).where(
            DerivedDaily.user_id == USER_ID, DerivedDaily.metric == gold.ASCENT
        )
    )
    assert found is None
