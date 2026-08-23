"""Executing a plan: Garmin → bronze, with the bookkeeping that makes it observable.

The shape of a run is deliberately boring. Load connection state (including any
cooldown a previous process earned), open a `sync_run`, walk the plan, write every
response to bronze, fetch detail for activities we have not seen, persist any refreshed
tokens, and close the run with a status the UI can render.

What it does *not* do is give up on the first error. A single endpoint failing — Garmin
retires one, a day 404s — degrades that endpoint, not the run: the rest of the window
still lands in bronze, and the run closes as `partial`. Only a rate limit, an auth
failure or the circuit breaker stop everything, because those are the three cases where
continuing makes things worse.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import GARMIN_TOKENS, RawPayload, SourceConnection, SyncRun
from vitals.ingest.raw_store import RawRecord, RawStore, StoreResult
from vitals.logging import get_logger
from vitals.security.vault import CredentialVault
from vitals.sources.base import DEGRADED, FAILED, PARTIAL, SUCCESS, SyncOutcome
from vitals.sources.garmin.client import GarminClient, GarminError, NeedsReauth, RateLimited
from vitals.sources.garmin.endpoints import split_dated
from vitals.sources.garmin.governor import (
    BudgetExhausted,
    CircuitOpen,
    GovernorState,
    RateGovernor,
    RateLimits,
)
from vitals.sources.garmin.plan import PlannedCall, plan_backfill, plan_incremental

log = get_logger(__name__)

SOURCE = "garmin"

# Detail fetched once per activity. The FIT file (`download_activity`) lands in phase 3
# together with Supabase Storage and the fitdecode parser.
ACTIVITY_DETAIL: tuple[tuple[str, str], ...] = (
    ("activity", "get_activity"),
    ("activity_details", "get_activity_details"),
    ("activity_splits", "get_activity_splits"),
)

ClientFactory = Callable[[str, RateGovernor], Awaitable[GarminClient]]


@dataclass
class _Progress:
    requests: int = 0
    result: StoreResult = StoreResult()
    failures: list[str] = field(default_factory=list)


class GarminSource:
    """The pull source. One instance per (user, sync run)."""

    name = SOURCE

    def __init__(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        vault: CredentialVault,
        client_factory: ClientFactory,
        limits: RateLimits | None = None,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._vault = vault
        self._client_factory = client_factory
        self._limits = limits or RateLimits()
        self._today = today
        self._store = RawStore(session, user_id=user_id, source=SOURCE)

    async def incremental(self, *, days: int = 7) -> SyncOutcome:
        return await self._run(plan_incremental(today=self._today(), days=days), kind="incremental")

    async def backfill(self, *, start: date, end: date) -> SyncOutcome:
        return await self._run(plan_backfill(start=start, end=end), kind="backfill")

    # ── the run ────────────────────────────────────────────────────────────────

    async def _run(self, plan: list[PlannedCall], *, kind: str) -> SyncOutcome:
        connection = await self._connection()
        governor = RateGovernor(
            limits=self._limits,
            state=GovernorState(
                consecutive_failures=connection.consecutive_failures,
                cooldown_until=connection.cooldown_until,
            ),
        )

        run = SyncRun(user_id=self._user_id, source=SOURCE, status="running")
        self._session.add(run)
        connection.last_attempt_at = datetime.now(UTC)
        await self._session.commit()

        log.info("garmin.sync_started", run_id=str(run.id), kind=kind, planned_calls=len(plan))
        outcome = await self._execute(plan, run_id=run.id, governor=governor, connection=connection)

        run.status = outcome.status
        run.requests_made = outcome.requests
        run.error = outcome.detail
        run.finished_at = datetime.now(UTC)
        connection.consecutive_failures = governor.state.consecutive_failures
        connection.cooldown_until = governor.state.cooldown_until
        if outcome.ok:
            connection.last_success_at = run.finished_at
        await self._session.commit()

        log.info(
            "garmin.sync_finished",
            run_id=str(run.id),
            status=outcome.status,
            requests=outcome.requests,
            stored=outcome.stored,
            unchanged=outcome.unchanged,
        )
        return outcome

    async def _execute(
        self,
        plan: list[PlannedCall],
        *,
        run_id: uuid.UUID,
        governor: RateGovernor,
        connection: SourceConnection,
    ) -> SyncOutcome:
        try:
            # Before connecting, not after: resuming a session is itself a network
            # call, and a run in cooldown should not spend even that.
            governor.check_ready()
        except CircuitOpen as exc:
            return await self._halt(connection, "degraded", DEGRADED, str(exc), governor)

        tokens = await self._vault.get(self._user_id, GARMIN_TOKENS)
        if not tokens:
            return await self._halt(
                connection,
                "needs_reauth",
                FAILED,
                "no stored Garmin tokens; run `vitals garmin login` locally",
                governor,
            )

        try:
            client = await self._client_factory(tokens, governor)
        except NeedsReauth as exc:
            return await self._halt(connection, "needs_reauth", FAILED, str(exc), governor)
        except (RateLimited, GarminError) as exc:
            return await self._halt(connection, "degraded", FAILED, str(exc), governor)

        progress = _Progress()
        stopped: str | None = None

        try:
            for call in plan:
                await self._execute_call(client, call, run_id=run_id, progress=progress)
            await self._sync_activities(client, plan, run_id=run_id, progress=progress)
        except NeedsReauth as exc:
            stopped = str(exc)
            connection.status = "needs_reauth"
        except (RateLimited, CircuitOpen, BudgetExhausted) as exc:
            # Not a failure of this run so much as a decision to stop making it worse.
            stopped = str(exc)
            connection.status = "degraded"
        finally:
            progress.requests = governor.requests_made
            await self._persist_tokens(client)

        return await self._finish(connection, progress, stopped, governor)

    async def _execute_call(
        self,
        client: GarminClient,
        call: PlannedCall,
        *,
        run_id: uuid.UUID,
        progress: _Progress,
    ) -> None:
        try:
            payload = await client.call(call.method, *call.args, **call.kwargs)
        except GarminError as exc:
            if isinstance(exc, NeedsReauth | RateLimited):
                raise
            # One endpoint failing is not the run failing: the rest of the window is
            # still worth having, and bronze makes the missing piece re-fetchable.
            log.warning("garmin.endpoint_failed", endpoint=call.endpoint, error=str(exc))
            progress.failures.append(f"{call.endpoint}: {exc}")
            return

        if payload is None or payload == [] or payload == {}:
            return

        records = self._records_for(call, payload)
        progress.result += await self._store.store(records, sync_run_id=run_id)

    def _records_for(self, call: PlannedCall, payload: Any) -> list[RawRecord]:
        """Explode one response into bronze rows, one per day where possible.

        Per-day rows are what make the trailing re-fetch cheap: a week-long response
        stored as a single blob would produce a new row every time any day in it
        changed, instead of one row for the day that actually changed.
        """
        if call.calendar_date is not None:
            return [RawRecord(call.endpoint, payload, calendar_date=call.calendar_date)]

        dated = split_dated(payload)
        if dated is not None:
            return [RawRecord(call.endpoint, item, calendar_date=day) for day, item in dated]

        # Unrecognised shape: keep it whole, filed under the window's end. Nothing is
        # lost — bronze is verbatim, and phase 3 is where payloads are interpreted.
        fallback = call.window[1] if call.window else None
        return [RawRecord(call.endpoint, payload, calendar_date=fallback)]

    async def _sync_activities(
        self,
        client: GarminClient,
        plan: list[PlannedCall],
        *,
        run_id: uuid.UUID,
        progress: _Progress,
    ) -> None:
        """Fetch detail for activities bronze has not seen before.

        Activity detail is immutable once recorded, so "already in bronze" is a
        sufficient reason to skip it — which is what keeps a daily run at a few dozen
        requests instead of re-fetching every activity in the trailing window.
        """
        if not any(call.endpoint == "activities" for call in plan):
            return

        known = await self._store.known_entity_keys("activity")
        summaries = await self._activity_summaries(run_id)

        for activity_id, day in summaries:
            if activity_id in known:
                continue
            for endpoint, method in ACTIVITY_DETAIL:
                try:
                    payload = await client.call(method, activity_id)
                except GarminError as exc:
                    if isinstance(exc, NeedsReauth | RateLimited):
                        raise
                    log.warning("garmin.activity_failed", activity_id=activity_id, error=str(exc))
                    progress.failures.append(f"{endpoint} {activity_id}: {exc}")
                    break
                if payload is None:
                    continue
                progress.result += await self._store.store(
                    [RawRecord(endpoint, payload, calendar_date=day, entity_key=activity_id)],
                    sync_run_id=run_id,
                )

    async def _activity_summaries(self, run_id: uuid.UUID) -> list[tuple[str, date | None]]:
        """Activity ids from the summaries this run just stored."""
        result = await self._session.execute(
            select(RawPayload.payload, RawPayload.calendar_date).where(
                RawPayload.user_id == self._user_id,
                RawPayload.source == SOURCE,
                RawPayload.endpoint == "activities",
                RawPayload.sync_run_id == run_id,
            )
        )
        summaries: list[tuple[str, date | None]] = []
        for payload, day in result.all():
            for item in payload if isinstance(payload, list) else [payload]:
                if not isinstance(item, dict):
                    continue
                activity_id = item.get("activityId")
                if activity_id is not None:
                    summaries.append((str(activity_id), day))
        return summaries

    # ── state transitions ──────────────────────────────────────────────────────

    async def _persist_tokens(self, client: GarminClient) -> None:
        """Capture the DI-token refresh the library performed in memory.

        With an inline-JSON tokenstore the library has nowhere to write a refreshed
        token, so if we do not read it back here it dies with the process — and the
        next run logs in through SSO from a datacenter IP.
        """
        try:
            tokens = client.export_tokens()
        except Exception as exc:  # noqa: BLE001 - never fail a run over bookkeeping
            log.warning("garmin.token_export_failed", error=str(exc))
            return
        if await self._vault.put(self._user_id, GARMIN_TOKENS, tokens):
            log.info("garmin.tokens_refreshed")

    async def _halt(
        self,
        connection: SourceConnection,
        status: str,
        run_status: str,
        detail: str,
        governor: RateGovernor,
    ) -> SyncOutcome:
        connection.status = status
        connection.status_detail = detail
        await self._session.commit()
        log.error("garmin.sync_halted", status=status, detail=detail)
        return SyncOutcome(status=run_status, requests=governor.requests_made, detail=detail)

    async def _finish(
        self,
        connection: SourceConnection,
        progress: _Progress,
        stopped: str | None,
        governor: RateGovernor,
    ) -> SyncOutcome:
        if stopped is not None:
            detail = stopped
            status = PARTIAL if progress.result.stored else DEGRADED
        elif progress.failures:
            detail = "; ".join(progress.failures[:5])
            status = PARTIAL
            connection.status = "active"
        else:
            detail = None
            status = SUCCESS
            connection.status = "active"

        connection.status_detail = detail
        await self._session.commit()
        return SyncOutcome(
            status=status,
            requests=progress.requests or governor.requests_made,
            stored=progress.result.stored,
            unchanged=progress.result.unchanged,
            detail=detail,
        )

    async def _connection(self) -> SourceConnection:
        result = await self._session.execute(
            select(SourceConnection).where(
                SourceConnection.user_id == self._user_id, SourceConnection.source == SOURCE
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            connection = SourceConnection(user_id=self._user_id, source=SOURCE, status="active")
            self._session.add(connection)
            await self._session.commit()
        return connection
