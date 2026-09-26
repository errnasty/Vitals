"""Bronze, for the things that are not JSON.

`raw_payload` holds every provider response verbatim because a payload not captured
today may be unobtainable tomorrow. A FIT file is that argument at its strongest: it
is the only artefact in the system that Garmin generated once, from the watch, and
would not regenerate — and it is served through the same unofficial API that could
close without notice.

So it is kept exactly as it arrived, gzipped, hash-deduped, and never parsed twice for
storage. Everything derived from it lives in silver and is rebuildable from here, which
is what makes a better decoder next year a recompute rather than a loss.

**Why the bytes live in Postgres rather than a bucket.** The whole history is a few
hundred megabytes at the volumes one person generates — a compressed FIT file is
around a hundred kilobytes, and a decade of daily training is under half a gigabyte.
Putting it here means it is inside the managed backups and the point-in-time recovery
that are already paid for, with no second service to provision, authenticate against,
or lose. The trade reverses once the artefacts are photographs rather than recordings;
phase 11 is where a bucket earns its place.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class RawFile(Base):
    __tablename__ = "raw_file"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # What the file is: 'fit' today, 'photo' when phase 11 arrives.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # The provider's own handle — an activity id, for everything so far.
    entity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    calendar_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Gzipped. Postgres would TOAST-compress this anyway, but doing it here means the
    # size recorded beside it is the real cost rather than a number off by 5x.
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Of the *uncompressed* bytes, so re-downloading an unchanged file is detectable
    # without depending on gzip producing byte-identical output across versions.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stored_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "source", "kind", "entity_key", name="uq_raw_file_entity"),
        Index("ix_raw_file_user_kind", "user_id", "kind"),
    )
