"""One row per (user, source): the connector's durable state.

Source-agnostic on purpose. Garmin (pull) uses `cooldown_until` and
`consecutive_failures` so a container restart cannot stampede past a rate limit the
previous run earned; HealthKit (push, phase 10) will use the same row for status and
last-seen without any schema change.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base

# `needs_reauth` is the one the UI turns into a banner: nothing will work until you
# run `vitals garmin login` again, and no amount of retrying will fix it.
CONNECTION_STATUSES = ("active", "degraded", "needs_reauth", "disabled")


class SourceConnection(Base):
    __tablename__ = "source_connection"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Garmin's display name — proof of which account the stored tokens belong to.
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "source", name="uq_source_connection_user_id_source"),
        CheckConstraint(
            "status in ('active', 'degraded', 'needs_reauth', 'disabled')",
            name="status_valid",
        ),
    )
