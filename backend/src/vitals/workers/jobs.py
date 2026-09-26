"""Jobs invoked by the Railway `sync` cron service.

Deliberately a separate entrypoint from the API: the sync job needs nothing but a
database URL and the encryption key, so it can be relocated to a home machine
unchanged if Garmin ever blocks datacenter IPs.

Railway's cron skips a tick when the previous run is still going rather than stacking
runs on top of each other, which is exactly the semantic a rate-limited scraper wants —
and the reason there is no in-process scheduler anywhere in this codebase.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.ai.brief import generate as write_brief
from vitals.analytics import recompute as recompute_gold
from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.ingest.pipeline import NoSuchUser, resolve_user, run_backfill, run_incremental
from vitals.insights.engine import refresh as refresh_insights
from vitals.logging import get_logger
from vitals.normalize import normalize as normalize_silver
from vitals.score import score as score_day
from vitals.sources.base import SyncOutcome

log = get_logger(__name__)


async def run_sync(
    source: str = "garmin", *, days: int = 7, email: str | None = None, normalize: bool = True
) -> SyncOutcome:
    """Incremental sync, then rebuild silver, gold and the score over the same window.

    All four belong together: a sync that fills bronze and leaves the layers above it
    behind means the dashboard keeps serving last week's numbers with no error
    anywhere to explain why. Every recompute is idempotent and cheap next to the
    network round trips the sync just made, so the cron does the lot by default.
    """
    if source != "garmin":
        raise ValueError(f"unknown source {source!r}")

    async with get_sessionmaker()() as session:
        outcome = await run_incremental(session, email=email, days=days)
        if normalize and outcome.ok:
            await _refresh_derived(session, source=source, email=email, days=days)
        if outcome.ok:
            await _resume_backfill(session, email=email)
        return outcome


async def _resume_backfill(session: AsyncSession, *, email: str | None) -> None:
    """Carry on any history pull the connect-time run did not finish.

    A backfill is a cursor rather than an operation, so there is nothing to recover
    here — whatever is left is simply the next window. Runs after the incremental
    sync so today's data is never waiting behind 2019's, and never fails the sync:
    a stalled history pull is a thinner dashboard, not a broken one.
    """
    from vitals.ingest import backfill

    try:
        user = await resolve_user(session, email=email)
    except NoSuchUser:
        return

    try:
        # An account that has never asked for history gets asked for here, so a
        # connection made before this existed still ends up with its archive.
        await backfill.ensure_requested(session, user_id=user.id)
        result = await backfill.run(session, user_id=user.id)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sync
        log.error("sync.backfill_failed", error=f"{type(exc).__name__}: {exc}")
        return

    if result.chunks:
        log.info(
            "sync.backfill_advanced",
            chunks=result.chunks,
            requests=result.requests,
            done=result.done,
            reached=result.cursor.isoformat() if result.cursor else None,
        )


async def _refresh_derived(
    session: AsyncSession, *, source: str, email: str | None, days: int
) -> None:
    """Rebuild silver then gold for the synced window. Never fails the sync it follows.

    Bronze is already safely written by this point, and it is the copy that cannot be
    re-fetched. A normalizer or a formula blowing up must not turn a successful
    capture into a failed run — either recompute can be re-run by hand at any time.

    Each layer only runs if the one below it succeeded: a training load derived from
    a half-written silver layer, or a score composed from a half-written gold one,
    produces a number that looks fine and is wrong. The daily brief is last for the
    same reason and one more: it is the only step that can spend money, and it should
    never do so describing a layer that failed to build.
    """
    try:
        user = await resolve_user(session, email=email)
    except NoSuchUser as exc:
        log.warning("sync.derived_skipped", reason=str(exc))
        return

    start = datetime.now(UTC).date() - timedelta(days=days)
    try:
        silver = await normalize_silver(session, user_id=user.id, source=source, start=start)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sync
        log.error("sync.silver_failed", error=f"{type(exc).__name__}: {exc}")
        return

    log.info(
        "sync.silver_refreshed",
        payloads=silver.payloads,
        rows=silver.rows,
        since=start.isoformat(),
    )

    try:
        gold = await recompute_gold(session, user_id=user.id, start=start)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sync
        log.error("sync.gold_failed", error=f"{type(exc).__name__}: {exc}")
        return

    log.info("sync.gold_refreshed", days=gold.days, rows=gold.rows)

    try:
        scored = await score_day(session, user_id=user.id, start=start)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sync
        log.error("sync.score_failed", error=f"{type(exc).__name__}: {exc}")
        return

    log.info("sync.score_refreshed", scored=scored.scored, trusted=scored.trusted)

    try:
        brief = await write_brief(session, user_id=user.id)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sync
        log.error("sync.brief_failed", error=f"{type(exc).__name__}: {exc}")
        return

    if brief is not None:
        # Re-running a sync that changed nothing costs nothing: the brief is keyed on
        # a hash of the digest, so an unchanged day is served from storage rather
        # than rewritten. Only a run that actually moved a number pays for a call.
        log.info(
            "sync.brief_refreshed",
            source=brief.source,
            reused=brief.reused,
            attempts=brief.attempts,
            tokens=brief.prompt_tokens + brief.completion_tokens,
        )

    try:
        # Cheap to skip and expensive to run: the engine's first act is to count
        # tagged days, so an account with nothing logged costs one query. Only an
        # account that can actually support a test pays for the permutations.
        found = await refresh_insights(session, user_id=user.id)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to the sync
        log.error("sync.insights_failed", error=f"{type(exc).__name__}: {exc}")
        return

    log.info(
        "sync.insights_refreshed",
        tested=found.tested,
        found=found.found,
        tagged_days=found.tagged_days,
        skipped=found.skipped,
    )


async def run_history(*, start: date, end: date, email: str | None = None) -> SyncOutcome:
    """One-off history pull. Manual by design — never put this on a cron."""
    async with get_sessionmaker()() as session:
        return await run_backfill(session, start=start, end=end, email=email)


async def shutdown() -> None:
    await dispose_engine()
