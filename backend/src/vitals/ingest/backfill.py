"""Pulling years of history without holding anything open for years.

A backfill is a few hundred rate-governed requests — ten minutes or so of mostly
waiting. That is longer than an HTTP request should live, longer than a sleeping
Railway container will stay awake, and long enough that a restart in the middle used
to mean starting again. So it is not one long operation. It is a cursor.

`source_connection.backfill_cursor` is the oldest day actually fetched. Each pass
walks it backwards a chunk at a time until it reaches `backfill_from` or runs out of
its time budget, and saves after every chunk. Whoever runs next — the task kicked off
when Garmin connects, or a cron tick six hours later — resumes from exactly there.
The work is idempotent either way, because bronze is hash-deduped: re-fetching a
window that was already stored costs the requests and writes nothing.

Backwards rather than forwards on purpose. The most recent weeks are the ones the
dashboard needs to show anything at all, so they arrive first and the app stops being
empty within a minute or two; the deep history fills in behind it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import get_settings
from vitals.ingest.pipeline import build_garmin_source, connection_for
from vitals.logging import get_logger
from vitals.sources.base import SyncOutcome
from vitals.sources.garmin import SOURCE

log = get_logger(__name__)

# One pass of the cursor. Small enough that a crash loses little and the first
# chunk lands quickly; large enough that the per-chunk overhead is noise.
CHUNK_DAYS = 180
# How long one invocation may keep working. The request that kicks this off has
# already returned, but the container is awake for the whole of it, and that is
# what a Railway bill is made of. The rest waits for the next pass.
DEFAULT_BUDGET_S = 300.0


@dataclass
class BackfillProgress:
    """Where a history pull has got to, in terms a screen can show."""

    requested_from: date | None
    cursor: date | None
    done: bool
    running: bool
    # 0..1, by days covered. None when nothing was ever requested.
    fraction: float | None
    days_remaining: int
    chunks: int = 0
    requests: int = 0
    detail: str | None = None


def _fraction(*, requested_from: date, cursor: date, end: date) -> float:
    total = (end - requested_from).days
    if total <= 0:
        return 1.0
    covered = (end - cursor).days
    return max(0.0, min(1.0, covered / total))


async def request(
    session: AsyncSession, *, user_id: uuid.UUID, years: int | None = None, end: date | None = None
) -> None:
    """Mark that a history pull is wanted, back to `years` before today.

    Called when a source connects. Does not fetch anything — it sets the cursor the
    passes below walk, so the caller is free to return immediately.
    """
    settings = get_settings()
    span = settings.backfill_years if years is None else years
    connection = await connection_for(session, user_id)
    if connection is None:  # pragma: no cover - a connection is written before this
        return

    # The anchor: the day the history was asked from, which is where the cursor
    # starts and what `progress` measures coverage against. The timestamp is
    # derived from it rather than read separately, so the two cannot disagree —
    # a caller passing an explicit `end` used to leave them days apart, and the
    # reported fraction was quietly wrong for as long as they differed.
    now = datetime.now(UTC)
    today = end or now.date()
    connection.backfill_from = today - timedelta(days=round(span * 365.25))
    connection.backfill_cursor = today
    connection.backfill_started_at = (
        now if end is None else datetime(today.year, today.month, today.day, tzinfo=UTC)
    )
    connection.backfill_finished_at = None
    await session.commit()

    log.info(
        "backfill.requested",
        since=connection.backfill_from.isoformat(),
        years=span,
    )


async def ensure_requested(
    session: AsyncSession, *, user_id: uuid.UUID, end: date | None = None
) -> bool:
    """Ask for history if nobody ever has. Returns True when this call asked.

    Self-healing, and it exists because of a real gap rather than as a precaution.
    The connect-time request landed in the same deploy as the migration that added
    these columns — so an account connected fifteen minutes earlier had no cursor to
    write, and nothing afterwards would ever notice. The incremental sync kept
    pulling its trailing week, forever, and the dashboard showed eight days of data
    with no error anywhere to explain why.

    An account with credentials and no history request is that state, whatever
    caused it. Asking here costs nothing when the answer is already recorded, and
    it means nobody has to reconnect to fix it — which matters, because
    reconnecting means another SSO attempt from a datacenter IP.
    """
    connection = await connection_for(session, user_id)
    if connection is None or connection.backfill_from is not None:
        return False

    await request(session, user_id=user_id, end=end)
    log.info("backfill.self_requested", reason="no history had ever been asked for")
    return True


async def progress(session: AsyncSession, *, user_id: uuid.UUID) -> BackfillProgress:
    connection = await connection_for(session, user_id)
    if connection is None or connection.backfill_from is None:
        return BackfillProgress(
            requested_from=None,
            cursor=None,
            done=False,
            running=False,
            fraction=None,
            days_remaining=0,
        )

    cursor = connection.backfill_cursor or connection.backfill_from
    done = connection.backfill_finished_at is not None or cursor <= connection.backfill_from
    end = connection.backfill_started_at.date() if connection.backfill_started_at else cursor
    return BackfillProgress(
        requested_from=connection.backfill_from,
        cursor=cursor,
        done=done,
        running=not done,
        fraction=1.0
        if done
        else _fraction(requested_from=connection.backfill_from, cursor=cursor, end=end),
        days_remaining=max(0, (cursor - connection.backfill_from).days),
    )


async def advance(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    budget_s: float = DEFAULT_BUDGET_S,
    chunk_days: int = CHUNK_DAYS,
    monotonic: object = None,
) -> BackfillProgress:
    """Work the cursor backwards until the history is covered or the budget is spent.

    Returns where it got to. Never raises for a Garmin failure: a history pull that
    stalls is a slower dashboard, not a broken one, and the cursor is saved so the
    next pass carries on from the same place.
    """
    clock = monotonic if callable(monotonic) else time.monotonic
    started = clock()

    connection = await connection_for(session, user_id)
    if connection is None or connection.backfill_from is None:
        return await progress(session, user_id=user_id)

    source = build_garmin_source(session, user_id=user_id)
    chunks = 0
    requests = 0
    detail: str | None = None

    while True:
        connection = await connection_for(session, user_id)
        if connection is None or connection.backfill_from is None:  # pragma: no cover
            break

        cursor = connection.backfill_cursor or connection.backfill_from
        if cursor <= connection.backfill_from:
            connection.backfill_finished_at = datetime.now(UTC)
            await session.commit()
            log.info("backfill.finished", chunks=chunks, requests=requests)
            break

        if clock() - started >= budget_s:
            detail = "paused for now — the next sync picks up where this left off"
            log.info("backfill.paused", chunks=chunks, requests=requests, cursor=cursor.isoformat())
            break

        start = max(connection.backfill_from, cursor - timedelta(days=chunk_days))
        outcome: SyncOutcome = await source.backfill(start=start, end=cursor)
        chunks += 1
        requests += outcome.requests

        if not outcome.ok:
            # Rate limited, or the breaker opened. The cursor stays where it is, so
            # the next pass retries this window rather than skipping a gap.
            detail = outcome.detail or f"stopped: {outcome.status}"
            log.warning("backfill.stopped", status=outcome.status, detail=outcome.detail)
            break

        # Saved every chunk: a container reclaimed mid-pull loses one window, not
        # the whole run.
        connection = await connection_for(session, user_id)
        if connection is not None:
            connection.backfill_cursor = start
            await session.commit()

    result = await progress(session, user_id=user_id)
    result.chunks = chunks
    result.requests = requests
    result.detail = detail
    return result


async def run(
    session: AsyncSession, *, user_id: uuid.UUID, budget_s: float = DEFAULT_BUDGET_S
) -> BackfillProgress:
    """Advance the history pull, then rebuild the layers over what arrived.

    The rebuild is what turns a successful pull into something on screen; without it
    the app would hold years of bronze and keep showing an empty dashboard.
    """
    result = await advance(session, user_id=user_id, budget_s=budget_s)
    if result.chunks:
        await rebuild(session, user_id=user_id, since=result.cursor)
    return result


async def rebuild(session: AsyncSession, *, user_id: uuid.UUID, since: date | None) -> None:
    """Silver → gold → score → brief over the window that just landed.

    Each layer is guarded the same way the cron guards them: a formula that blows up
    must not lose the bronze that was just captured, which is the only part that
    cannot be fetched again.
    """
    from vitals.ai.brief import generate as write_brief
    from vitals.analytics import recompute as recompute_gold
    from vitals.normalize import normalize as normalize_silver
    from vitals.score import score as score_day

    try:
        await normalize_silver(session, user_id=user_id, source=SOURCE, start=since)
        await recompute_gold(session, user_id=user_id, start=since)
        await score_day(session, user_id=user_id, start=since)
        await write_brief(session, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the pull
        log.error("backfill.rebuild_failed", error=f"{type(exc).__name__}: {exc}")
