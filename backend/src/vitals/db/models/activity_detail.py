"""Silver: what the recording knew that the summary did not.

A separate table from `activity` rather than more columns on it, because the two have
different lifetimes and different failure modes. The summary arrives with every sync
and is complete for every activity ever recorded; this arrives only for activities
whose FIT file has been downloaded and successfully decoded, which will always be a
subset — an older activity may predate the backfill, a file may be corrupt, a manual
entry has no recording at all.

Keeping them apart means "no detail" is a missing row rather than a dozen nulls spread
through the summary, and a decoder rewrite drops and rebuilds this table without
touching the summary that the rest of the app depends on.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
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


class ActivityDetail(Base):
    __tablename__ = "activity_detail"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("activity.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    samples: Mapped[int] = mapped_column(Integer, nullable=False)
    # Garmin's "smart recording" is not 1Hz, and a window measured in samples would
    # mean different things on different devices.
    sample_interval_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    normalized_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    variability_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Friel's aerobic decoupling: positive means the second half cost more heartbeats
    # for the same speed.
    decoupling_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_drift_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)

    ascent_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    descent_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_time_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    # An SVG path in the design system's 380x300 box, projected in Python like every
    # other value a component receives.
    route_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id", name="uq_activity_detail_activity"),
    )
