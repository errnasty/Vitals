"""Binary bronze: storing a file exactly as it arrived, once.

The JSON store next door dedupes by content hash so a daily re-fetch of an unrevised
window writes nothing. The same argument applies here and matters more, because the
files are four orders of magnitude larger: re-downloading an activity whose recording
has not changed must cost the request and nothing else.

Where the two differ is what happens when the content *does* change. A revised JSON
payload lands beside the old one, giving a revision history for free. A FIT file is
the watch's original recording and does not get revised — if the bytes differ, the
download was truncated or the file was re-encoded, and keeping both copies of a
hundred kilobytes to record that would cost real storage for no information. So this
one updates in place.
"""

from __future__ import annotations

import gzip
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import RawFile
from vitals.logging import get_logger

log = get_logger(__name__)

# gzip's default. Level 9 buys a few percent on a format that is already mostly
# packed binary, for several times the CPU on a container billed by the second.
COMPRESSION = 6


@dataclass(frozen=True, slots=True)
class Stored:
    file_id: uuid.UUID
    fresh: bool
    original_bytes: int
    stored_bytes: int


async def put(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str,
    kind: str,
    entity_key: str,
    content: bytes,
    calendar_date: date | None = None,
) -> Stored:
    """Store a file, or recognise that this exact file is already here."""
    digest = hashlib.sha256(content).hexdigest()

    existing = await session.scalar(
        select(RawFile).where(
            RawFile.user_id == user_id,
            RawFile.source == source,
            RawFile.kind == kind,
            RawFile.entity_key == entity_key,
        )
    )

    if existing is not None and existing.content_hash == digest:
        existing.last_seen_at = datetime.now(UTC)
        await session.commit()
        return Stored(
            file_id=existing.id,
            fresh=False,
            original_bytes=existing.original_bytes,
            stored_bytes=existing.stored_bytes,
        )

    packed = gzip.compress(content, compresslevel=COMPRESSION)

    if existing is not None:
        existing.content = packed
        existing.content_hash = digest
        existing.stored_bytes = len(packed)
        existing.original_bytes = len(content)
        existing.calendar_date = calendar_date
        existing.last_seen_at = datetime.now(UTC)
        await session.commit()
        return Stored(
            file_id=existing.id,
            fresh=True,
            original_bytes=len(content),
            stored_bytes=len(packed),
        )

    row = RawFile(
        user_id=user_id,
        source=source,
        kind=kind,
        entity_key=entity_key,
        calendar_date=calendar_date,
        content=packed,
        content_hash=digest,
        stored_bytes=len(packed),
        original_bytes=len(content),
    )
    session.add(row)
    await session.commit()
    return Stored(file_id=row.id, fresh=True, original_bytes=len(content), stored_bytes=len(packed))


async def read(session: AsyncSession, file_id: uuid.UUID) -> bytes | None:
    """The original bytes back, uncompressed."""
    row = await session.get(RawFile, file_id)
    return None if row is None else gzip.decompress(row.content)


async def known_keys(
    session: AsyncSession, *, user_id: uuid.UUID, source: str, kind: str
) -> set[str]:
    """Which entities already have a file, so the sync can skip re-downloading them."""
    rows = (
        await session.execute(
            select(RawFile.entity_key).where(
                RawFile.user_id == user_id, RawFile.source == source, RawFile.kind == kind
            )
        )
    ).scalars()
    return set(rows)
