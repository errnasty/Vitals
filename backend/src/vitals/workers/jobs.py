"""Jobs invoked by the Railway `sync` cron service.

Deliberately a separate entrypoint from the API: the sync job needs nothing but a
database URL and the encryption key, so it can be relocated to a home machine
unchanged if Garmin ever blocks datacenter IPs.

Railway's cron skips a tick when the previous run is still going rather than stacking
runs on top of each other, which is exactly the semantic a rate-limited scraper wants —
and the reason there is no in-process scheduler anywhere in this codebase.
"""

from __future__ import annotations

from datetime import date

from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.ingest.pipeline import run_backfill, run_incremental
from vitals.logging import get_logger
from vitals.sources.base import SyncOutcome

log = get_logger(__name__)


async def run_sync(
    source: str = "garmin", *, days: int = 7, email: str | None = None
) -> SyncOutcome:
    """Incremental sync. The trailing window catches Garmin's retroactive revisions."""
    if source != "garmin":
        raise ValueError(f"unknown source {source!r}")

    async with get_sessionmaker()() as session:
        return await run_incremental(session, email=email, days=days)


async def run_history(*, start: date, end: date, email: str | None = None) -> SyncOutcome:
    """One-off history pull. Manual by design — never put this on a cron."""
    async with get_sessionmaker()() as session:
        return await run_backfill(session, start=start, end=end, email=email)


async def shutdown() -> None:
    await dispose_engine()
