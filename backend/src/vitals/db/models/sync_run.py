"""Sync run bookkeeping — the observability spine of the ingestion layer.

Written by every source (pull or push) so the UI can show sync health and the rate
governor can tell a degraded source from a healthy one across process restarts.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base

SYNC_STATUSES = ("running", "success", "partial", "degraded", "failed")


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable because a push source (phase 10) can land data before anyone has
    # signed in; multi-user from day one at the schema level.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    requests_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('running', 'success', 'partial', 'degraded', 'failed')",
            name="status_valid",
        ),
        Index("ix_sync_run_user_source_started", "user_id", "source", "started_at"),
    )
