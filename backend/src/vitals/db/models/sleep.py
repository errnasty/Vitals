"""Silver: one night's sleep.

Kept as its own table rather than a handful of `metric_daily` rows because a night is
a *thing* with a start, an end and a structure — phase 4 asks questions like "how much
deep sleep in the first half" that a pile of scalars cannot answer. The headline
numbers are ALSO written to `metric_daily`, so a chart of sleep duration over a year
does not have to know this table exists.

Garmin files a night under the calendar date you woke up on, and that convention is
kept: `calendar_date` is the provider's own `calendarDate`, while `started_at` and
`ended_at` are UTC instants.
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
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class SleepSession(Base):
    __tablename__ = "sleep_session"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nap_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_hrv: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_spo2: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_respiration: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("raw_payload.id", ondelete="SET NULL"), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "source", "calendar_date", name="uq_sleep_session_night"),
        Index("ix_sleep_session_user_date", "user_id", "calendar_date"),
    )
