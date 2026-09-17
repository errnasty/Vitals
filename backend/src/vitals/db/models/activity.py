"""Silver: one recorded activity.

Keyed by the provider's own id (`external_id`) rather than by time, because that is
the only stable handle: Garmin revises an activity's summary after the fact when a
device syncs late or you edit it in Connect, and matching on start time would create a
duplicate instead of updating the original.

Units are canonical here too — seconds, metres, kcal — so phase 4 can sum a week of
training load without a unit lookup per row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Garmin's activityId, as a string so a provider that uses UUIDs still fits.
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Garmin's `typeKey`: 'running', 'cycling', 'lap_swimming', 'strength_training'.
    activity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)

    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)

    avg_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_power: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Garmin's own training effect, kept as reported. Phase 4 computes its own load
    # from first principles; this is the provider's opinion, useful for calibration.
    aerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_volume_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("raw_payload.id", ondelete="SET NULL"), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_activity_external"),
        Index("ix_activity_user_started", "user_id", "started_at"),
    )
