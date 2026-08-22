"""Jobs invoked by the Railway `sync` cron service.

Deliberately a separate entrypoint from the API: the sync job needs nothing but a
database URL and the encryption key, so it can be relocated to a home machine
unchanged if Garmin ever blocks datacenter IPs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from vitals.db.models import SyncRun
from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.logging import get_logger

log = get_logger(__name__)


async def run_sync(source: str = "garmin") -> uuid.UUID:
    """Phase 0 placeholder: opens a sync_run, closes it, proves the write path works.

    Phase 2 replaces the body with the governed Garmin fetchers; the bookkeeping
    around it is already what it will need.
    """
    async with get_sessionmaker()() as session:
        run = SyncRun(source=source, status="running")
        session.add(run)
        await session.commit()
        log.info("sync.started", run_id=str(run.id), source=source)

        run.status = "success"
        run.finished_at = datetime.now(UTC)
        run.requests_made = 0
        await session.commit()
        log.info("sync.finished", run_id=str(run.id), source=source, status=run.status)
        return run.id


async def last_sync(source: str | None = None) -> SyncRun | None:
    async with get_sessionmaker()() as session:
        stmt = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
        if source:
            stmt = stmt.where(SyncRun.source == source)
        return (await session.execute(stmt)).scalar_one_or_none()


async def shutdown() -> None:
    await dispose_engine()
