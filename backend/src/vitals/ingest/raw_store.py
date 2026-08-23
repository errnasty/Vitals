"""Writing bronze: verbatim provider JSON, deduplicated by content hash.

One method, `store`, and the whole daily-resync economics fall out of it. A trailing
7-day window re-fetched every few hours costs a handful of requests and, on the days
Garmin has not revised, zero new rows.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import RawPayload
from vitals.logging import get_logger

log = get_logger(__name__)


def payload_hash(payload: Any) -> str:
    """Content hash of a payload.

    Canonical JSON — sorted keys, no incidental whitespace — so a provider reordering
    its keys is not mistaken for a revision, and the same payload always hashes the
    same across processes and releases.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One payload destined for bronze."""

    endpoint: str
    payload: Any
    calendar_date: date | None = None
    entity_key: str | None = None


@dataclass(frozen=True, slots=True)
class StoreResult:
    stored: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.stored + self.unchanged

    def __add__(self, other: StoreResult) -> StoreResult:
        return StoreResult(self.stored + other.stored, self.unchanged + other.unchanged)


class RawStore:
    def __init__(self, session: AsyncSession, *, user_id: uuid.UUID, source: str) -> None:
        self._session = session
        self._user_id = user_id
        self._source = source

    async def store(
        self, records: Sequence[RawRecord], *, sync_run_id: uuid.UUID | None = None
    ) -> StoreResult:
        """Insert every unseen version; bump `last_seen_at` on the ones already held.

        `ON CONFLICT DO UPDATE` rather than a read-then-write: the upsert is atomic, so
        two overlapping syncs cannot race into a duplicate, and one statement covers the
        whole batch.
        """
        if not records:
            return StoreResult()

        rows = [
            {
                "id": uuid.uuid4(),
                "user_id": self._user_id,
                "source": self._source,
                "endpoint": record.endpoint,
                "calendar_date": record.calendar_date,
                "entity_key": record.entity_key,
                "payload": record.payload,
                "payload_hash": payload_hash(record.payload),
                "sync_run_id": sync_run_id,
            }
            for record in records
        ]
        # A batch can legitimately contain the same version twice (overlapping windows
        # from two endpoints); Postgres refuses to touch a row twice in one statement,
        # so collapse duplicates here first.
        deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            key = (row["endpoint"], row["calendar_date"], row["entity_key"], row["payload_hash"])
            deduped.setdefault(key, row)

        upsert = (
            pg_insert(RawPayload)
            .values(list(deduped.values()))
            .on_conflict_do_update(
                constraint="uq_raw_payload_version",
                set_={"last_seen_at": func.now()},
            )
            .returning(RawPayload.first_seen_at, RawPayload.last_seen_at)
        )

        result = await self._session.execute(upsert)
        stored = sum(1 for first, last in result.all() if first == last)
        await self._session.commit()

        outcome = StoreResult(stored=stored, unchanged=len(deduped) - stored)
        log.debug(
            "bronze.stored",
            source=self._source,
            endpoints=sorted({r.endpoint for r in records}),
            stored=outcome.stored,
            unchanged=outcome.unchanged,
        )
        return outcome

    async def known_entity_keys(self, endpoint: str) -> set[str]:
        """Entity keys already in bronze — what makes activity fetching incremental."""
        result = await self._session.execute(
            select(RawPayload.entity_key)
            .where(
                RawPayload.user_id == self._user_id,
                RawPayload.source == self._source,
                RawPayload.endpoint == endpoint,
                RawPayload.entity_key.is_not(None),
            )
            .distinct()
        )
        return {key for key in result.scalars() if key is not None}

    async def count(self, endpoint: str | None = None) -> int:
        statement = select(func.count()).where(
            RawPayload.user_id == self._user_id, RawPayload.source == self._source
        )
        if endpoint is not None:
            statement = statement.where(RawPayload.endpoint == endpoint)
        return (await self._session.execute(statement)).scalar_one()

    async def date_range(self) -> tuple[date | None, date | None]:
        """Earliest and latest day held — the honest answer to "did the backfill work"."""
        result = await self._session.execute(
            select(func.min(RawPayload.calendar_date), func.max(RawPayload.calendar_date)).where(
                RawPayload.user_id == self._user_id, RawPayload.source == self._source
            )
        )
        first, last = result.one()
        return first, last
