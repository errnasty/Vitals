"""The whole connector, end to end, against a fake Garmin and a real Postgres.

Everything except the network is real here: the plan, the governor, the bronze store,
the connection state machine and the token round-trip. What the fake replaces is the
one thing that needs a Garmin account — which is exactly the part that cannot be tested
anywhere but against Garmin itself.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import GARMIN_TOKENS, AppUser, RawPayload, SourceConnection, SyncRun
from vitals.security.vault import EncryptedDbVault
from vitals.sources.garmin.client import GarminError, NeedsReauth, RateLimited
from vitals.sources.garmin.governor import RateLimits
from vitals.sources.garmin.source import GarminSource

KEY = Fernet.generate_key().decode()
TOKENS = '{"di_token": "a", "di_refresh_token": "b", "di_client_id": "c"}'
TODAY = date(2026, 8, 23)

# No delays: the governor's timing is covered in test_garmin_governor.py.
FAST = RateLimits(min_delay_s=0, max_delay_s=0, burst=10_000, requests_per_minute=1e6)


class FakeGarmin:
    """Stands in for GarminClient: records calls, returns canned payloads."""

    def __init__(
        self,
        *,
        activities: list[dict[str, Any]] | None = None,
        errors: dict[str, Exception] | None = None,
        tokens: str = TOKENS,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.activities = activities if activities is not None else []
        self.errors = errors or {}
        self.tokens = tokens
        self.display_name = "test-user"
        self.governor: Any = None

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        # The real client governs every call; the fake must too, or the governor's
        # budget, breaker and cooldown would go untested at this level.
        if self.governor is not None:
            await self.governor.acquire()
        self.calls.append((method, args))
        if method in self.errors:
            raise self.errors[method]
        if method == "get_activities_by_date":
            return self.activities
        if method in ("get_activity", "get_activity_details", "get_activity_splits"):
            return {"activityId": int(args[0]), "detail": method}
        if len(args) == 2:  # a range endpoint
            start, end = date.fromisoformat(args[0]), date.fromisoformat(args[1])
            days = (end - start).days + 1
            return [
                {"calendarDate": (start + timedelta(days=i)).isoformat(), "value": 40 + i}
                for i in range(days)
            ]
        return {"day": args[0] if args else None, "value": 1}

    def export_tokens(self) -> str:
        return self.tokens

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)


async def _source(
    session: AsyncSession, user: AppUser, client: FakeGarmin, **kwargs: Any
) -> GarminSource:
    vault = EncryptedDbVault(session, KEY)
    await vault.put(user.id, GARMIN_TOKENS, TOKENS)

    async def factory(tokens: str, governor: Any) -> Any:
        assert tokens == TOKENS  # the stored tokens are what a run resumes from
        client.governor = governor
        return client

    return GarminSource(
        session,
        user_id=user.id,
        vault=vault,
        client_factory=factory,
        limits=FAST,
        today=lambda: TODAY,
        **kwargs,
    )


async def _connection(session: AsyncSession, user: AppUser) -> SourceConnection:
    return (
        await session.execute(select(SourceConnection).where(SourceConnection.user_id == user.id))
    ).scalar_one()


async def test_a_sync_lands_one_bronze_row_per_day(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)

    outcome = await source.incremental(days=7)

    assert outcome.status == "success"
    assert outcome.stored > 0
    rows = (
        (await pg_session.execute(select(RawPayload).where(RawPayload.endpoint == "rhr_daily")))
        .scalars()
        .all()
    )
    # The week arrived as one response and was split into a row per day.
    assert len(rows) == 7
    assert {row.calendar_date for row in rows} == {TODAY - timedelta(days=i) for i in range(7)}


async def test_the_second_sync_of_an_unchanged_week_stores_nothing(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """The economics of the trailing window: same requests, no new rows."""
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)

    first = await source.incremental(days=7)
    second = await source.incremental(days=7)

    assert first.stored > 0
    assert second.stored == 0
    assert second.unchanged == first.stored + first.unchanged
    assert second.status == "success"


async def test_a_revised_day_is_captured_beside_the_original(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)
    await source.incremental(days=2)

    # Garmin recomputes a sleep score after the fact.
    class Revised(FakeGarmin):
        async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
            result = await super().call(method, *args, **kwargs)
            if method == "get_sleep_daily":
                for item in result:
                    item["value"] = 99
            return result

    revised = Revised()
    source = await _source(pg_session, pg_user, revised)
    outcome = await source.incremental(days=2)

    rows = (
        (
            await pg_session.execute(
                select(RawPayload).where(
                    RawPayload.endpoint == "sleep_daily", RawPayload.calendar_date == TODAY
                )
            )
        )
        .scalars()
        .all()
    )
    assert outcome.stored == 2  # both days of the revised endpoint
    assert len(rows) == 2  # original and revision, side by side


async def test_activity_detail_is_fetched_once_and_then_skipped(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """What keeps a daily run at a few dozen requests instead of re-fetching everything."""
    activities = [{"activityId": 555, "startTimeLocal": "2026-08-22 07:00:00"}]
    client = FakeGarmin(activities=activities)
    source = await _source(pg_session, pg_user, client)

    await source.incremental(days=7)
    assert client.count("get_activity") == 1
    assert client.count("get_activity_details") == 1
    assert client.count("get_activity_splits") == 1

    again = FakeGarmin(activities=activities)
    source = await _source(pg_session, pg_user, again)
    await source.incremental(days=7)

    assert again.count("get_activity") == 0


async def test_one_failing_endpoint_does_not_lose_the_rest_of_the_window(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    client = FakeGarmin(errors={"get_hrv_data_range": GarminError("500 from Garmin")})
    source = await _source(pg_session, pg_user, client)

    outcome = await source.incremental(days=7)

    assert outcome.status == "partial"
    assert outcome.stored > 0
    assert "hrv_range" in (outcome.detail or "")
    assert await _connection(pg_session, pg_user) is not None


async def test_a_rate_limit_stops_the_run_and_persists_a_cooldown(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    client = FakeGarmin(errors={"get_sleep_daily": RateLimited("429")})
    source = await _source(pg_session, pg_user, client)

    outcome = await source.incremental(days=7)
    connection = await _connection(pg_session, pg_user)

    assert outcome.status in ("partial", "degraded")
    assert connection.status == "degraded"
    assert connection.cooldown_until is None or connection.cooldown_until > datetime.now(UTC)


async def test_a_persisted_cooldown_blocks_the_next_run(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """A redeploy mid-cooldown must not start hammering again."""
    connection = SourceConnection(
        user_id=pg_user.id,
        source="garmin",
        status="degraded",
        cooldown_until=datetime.now(UTC) + timedelta(hours=1),
    )
    pg_session.add(connection)
    await pg_session.commit()

    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)
    outcome = await source.incremental(days=7)

    assert client.calls == []
    assert outcome.status == "degraded"


async def test_rejected_tokens_ask_for_a_relogin_and_stop(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Re-authenticating from here would be an SSO login from a datacenter IP."""
    client = FakeGarmin(errors={"get_rhr_daily": NeedsReauth("401")})
    source = await _source(pg_session, pg_user, client)

    outcome = await source.incremental(days=7)

    assert (await _connection(pg_session, pg_user)).status == "needs_reauth"
    assert outcome.status in ("degraded", "partial")
    assert client.count("get_sleep_daily") == 0  # stopped immediately


async def test_a_sync_without_stored_tokens_fails_before_calling_garmin(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)
    await EncryptedDbVault(pg_session, KEY).delete(pg_user.id, GARMIN_TOKENS)

    outcome = await source.incremental(days=7)

    assert outcome.status == "failed"
    assert "garmin login" in (outcome.detail or "")
    assert client.calls == []


async def test_a_refreshed_token_is_captured(pg_session: AsyncSession, pg_user: AppUser) -> None:
    """With an inline-JSON tokenstore the library cannot persist its own refresh.

    If this is not read back after the run it dies with the process, and the next sync
    falls back to an SSO login — the single most consequential detail in this phase.
    """
    refreshed = '{"di_token": "NEW", "di_refresh_token": "b", "di_client_id": "c"}'
    client = FakeGarmin(tokens=refreshed)
    source = await _source(pg_session, pg_user, client)

    await source.incremental(days=1)

    assert await EncryptedDbVault(pg_session, KEY).get(pg_user.id, GARMIN_TOKENS) == refreshed


async def test_unchanged_tokens_are_not_rewritten(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)
    await source.incremental(days=1)

    from vitals.db.models import Credential

    row = (await pg_session.execute(select(Credential))).scalar_one()
    written_at = row.updated_at

    await source.incremental(days=1)
    await pg_session.refresh(row)

    assert row.updated_at == written_at


async def test_every_run_is_recorded(pg_session: AsyncSession, pg_user: AppUser) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)

    outcome = await source.incremental(days=7)
    run = (await pg_session.execute(select(SyncRun))).scalar_one()

    assert run.status == outcome.status == "success"
    assert run.requests_made == outcome.requests == len(client.calls)
    assert run.user_id == pg_user.id
    assert run.finished_at is not None


async def test_bronze_rows_are_traceable_to_their_run(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    source = await _source(pg_session, pg_user, FakeGarmin())
    await source.incremental(days=1)

    run = (await pg_session.execute(select(SyncRun))).scalar_one()
    rows = (await pg_session.execute(select(RawPayload))).scalars().all()

    assert rows and all(row.sync_run_id == run.id for row in rows)


async def test_backfill_lands_years_of_history(pg_session: AsyncSession, pg_user: AppUser) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)

    outcome = await source.backfill(start=date(2024, 8, 23), end=TODAY)

    from vitals.ingest.raw_store import RawStore

    first, last = await RawStore(pg_session, user_id=pg_user.id, source="garmin").date_range()
    assert outcome.status == "success"
    assert first == date(2024, 8, 23)
    assert last == TODAY
    # Two years of daily rows from range endpoints, not two years of requests.
    assert outcome.stored > 700
    assert outcome.requests < 200


@pytest.mark.parametrize("days", [1, 7, 30])
async def test_the_window_size_is_honoured(
    pg_session: AsyncSession, pg_user: AppUser, days: int
) -> None:
    client = FakeGarmin()
    source = await _source(pg_session, pg_user, client)
    await source.incremental(days=days)

    rows = (
        (await pg_session.execute(select(RawPayload).where(RawPayload.endpoint == "rhr_daily")))
        .scalars()
        .all()
    )
    assert len(rows) == days
