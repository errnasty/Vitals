"""Bronze: provider JSON exactly as it arrived, kept forever.

This is the safety net the whole design rests on. Everything in silver and gold is
re-derivable from here, so a normalizer bug is a recompute rather than data loss — and
because the Garmin API is unofficial and could break or vanish, a payload not captured
today may be unobtainable tomorrow.

Two properties make the daily trailing re-fetch nearly free:

* rows are keyed by content hash, so re-fetching a window Garmin has not revised
  inserts nothing and merely bumps `last_seen_at`;
* when Garmin *does* revise a day retroactively — and it does, for sleep scores and
  training status — the new version lands beside the old one instead of overwriting it,
  giving a revision history nobody had to design for.

The unique constraint uses NULLS NOT DISTINCT (PG15+): `calendar_date` and `entity_key`
are legitimately null for undated payloads, and under default NULL semantics those rows
would never collide and would be re-inserted on every sync.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class RawPayload(Base):
    __tablename__ = "raw_payload"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # The logical endpoint, not the URL: 'sleep_daily', 'training_readiness', 'activity'.
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Derived from the request window, never from the provider's *Local fields, which
    # the library documents as double-offset on some accounts.
    calendar_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Activity id and similar non-date keys.
    entity_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sync_run.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source",
            "endpoint",
            "calendar_date",
            "entity_key",
            "payload_hash",
            name="uq_raw_payload_version",
            postgresql_nulls_not_distinct=True,
        ),
        # The read pattern for phase 3: every version of one endpoint over a window.
        Index(
            "ix_raw_payload_user_source_endpoint_date",
            "user_id",
            "source",
            "endpoint",
            "calendar_date",
        ),
    )
