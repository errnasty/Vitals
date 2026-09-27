"""Gold: the constants this person's own data supports.

One row per trait, with the evidence beside it. The evidence columns are not
decoration — a personalised constant without a sample size is indistinguishable from
a made-up one, and this table exists precisely so a screen can say "your maximum heart
rate, from 340 recorded activities" rather than "your maximum heart rate".

Traits are replaced wholesale on each fit, never merged. A trait that no longer has
the observations behind it has to disappear rather than linger at last year's value,
for the same reason a finding that stops holding has to disappear from the insights
table: a stale personalised constant is worse than none, because the app keeps acting
on it and nothing says it is out of date.
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


class ResponseTrait(Base):
    __tablename__ = "response_trait"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )

    # A name from `profile/canonical.py`.
    trait: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    # How many observations it was measured from. The whole point of this table.
    observations: Mapped[int] = mapped_column(Integer, nullable=False)
    # One sentence naming what it was measured from, written in Python so a screen
    # never has to explain a number it did not compute.
    basis: Mapped[str] = mapped_column(Text, nullable=False)

    fitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "trait", name="uq_response_trait"),)
