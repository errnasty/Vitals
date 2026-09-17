"""Silver: one number, one day (or one instant), in canonical units.

Source-agnostic by construction. `source` is kept on the row rather than resolved away
at write time, so a day covered by both a Garmin watch and an iPhone keeps both
readings and the resolver decides which one analytics sees. Throwing one away at
ingest would be unrecoverable; keeping both costs a column.

Provenance is a column too: `raw_payload_id` points at the exact bronze row this value
came from. That is what makes a normalizer bug debuggable a year later — the number
in silver is never the only copy, and you can always ask what it was derived from.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class MetricDaily(Base):
    """One canonical metric for one calendar day, from one source."""

    __tablename__ = "metric_daily"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    # A name from vitals.normalize.canonical, never a provider's own key.
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("raw_payload.id", ondelete="SET NULL"), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "metric", "calendar_date", "source", name="uq_metric_daily_point"
        ),
        # The read pattern for phases 4-5: one metric across a window, every source.
        Index("ix_metric_daily_user_metric_date", "user_id", "metric", "calendar_date"),
    )


class MetricSample(Base):
    """One intraday reading — stress every few minutes, body battery, SpO2.

    Only ever written for days the intraday endpoints actually covered. Backfill does
    not fetch them (one request per endpoint per day would be thousands), so this table
    is dense for recent history and empty further back, which is a deliberate trade
    rather than a gap to fix.
    """

    __tablename__ = "metric_sample"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    # Always UTC. The calendar date is derived from the user's timezone when needed,
    # never taken from a provider's *Local field.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("raw_payload.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "metric", "recorded_at", "source", name="uq_metric_sample_point"
        ),
        Index("ix_metric_sample_user_metric_time", "user_id", "metric", "recorded_at"),
    )
