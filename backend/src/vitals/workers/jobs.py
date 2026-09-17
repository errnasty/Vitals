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

from vitals.analytics import recompute as recompute_gold
from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.ingest.pipeline import NoSuchUser, resolve_user, run_backfill, run_incremental
from vitals.logging import get_logger
from vitals.normalize import normalize as normalize_silver
from vitals.sources.base import SyncOutcome

log = get_logger(__name__)


async def run_sync(
    source: str = "garmin", *, days: int = 7, email: str | None = None, normalize: bool = True
) -> SyncOutcome:
    """Incremental sync, then rebuild silver and gold over the same window.

    All three belong together: a sync that fills bronze and leaves the layers above it
    behind means the dashboard keeps serving last week's numbers with no error
    anywhere to explain why. Both recomputes are idempotent and cheap next to the
    network round trips the sync just made, so the cron does the lot by default.
    """
    if source != "garmin":
        raise ValueError(f"unknown source {source!r}")

    async with get_sessionmaker()() as session:
        outcome = await run_incremental(session, email=email, days=days)
        if normalize and outcome.ok:
            await _refresh_derived(session, source=source, email=email, days=days)
        return outcome


async def _refresh_derived(
    session: AsyncSession, *, source: str, email: str | None, days: int
) -> None:
    """Rebuild silver then gold for the synced window. Never fails the sync it follows.

    Bronze is already safely written by this point, and it is the copy that cannot be
    re-fetched. A normalizer or a formula blowing up must not turn a successful
    capture into a failed run — either recompute can be re-run by hand at any time.

    Gold only runs if silver succeeded: deriving a training load from a half-written
    silver layer would produce a number that looks fine and is wrong.
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


async def run_history(*, start: date, end: date, email: str | None = None) -> SyncOutcome:
    """One-off history pull. Manual by design — never put this on a cron."""
    async with get_sessionmaker()() as session:
        return await run_backfill(session, start=start, end=end, email=email)


async def shutdown() -> None:
    await dispose_engine()
