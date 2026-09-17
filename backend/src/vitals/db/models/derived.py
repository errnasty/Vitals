"""Gold: what the observations mean, with an honest note on how much they rest on.

No `source` column, unlike silver. By the time a value reaches gold the resolver has
already chosen between devices, so a derived number belongs to the person rather than
to any watch. Recomputing is how you change your mind about that choice.

`coverage` is the column that keeps the whole layer honest. A 42-day fitness figure
computed from 41 days and one computed from 6 are both a number, and nothing about the
number itself says which you are holding. Phase 5 refuses to let a pillar count for
more than its coverage allows, and this is where it reads that from.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
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


class DerivedDaily(Base):
    __tablename__ = "derived_daily"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    # A name from vitals.analytics.canonical.
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)

    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    # Fraction of the metric's window that actually held an observation, 0..1.
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    # The raw count behind that fraction, kept because "3 of 42" explains itself in a
    # way "0.07" does not.
    inputs: Mapped[int] = mapped_column(Integer, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "metric", "calendar_date", name="uq_derived_daily_point"),
        CheckConstraint("coverage >= 0 and coverage <= 1", name="coverage_is_a_fraction"),
        Index("ix_derived_daily_user_metric_date", "user_id", "metric", "calendar_date"),
    )
