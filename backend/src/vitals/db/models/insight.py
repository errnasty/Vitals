"""Findings: what the analysis concluded, and what it took to conclude it.

Stored rather than computed on request for two reasons. A refresh is a few hundred
permutation tests and takes seconds, which is fine for a nightly job and far too slow
for a page load. And a finding is a claim about someone's health — writing it down
with the sample size, the effect and the p-value behind it means it can be checked
later, argued with, and shown to have changed its mind.

`tested` is the one column people forget. Three findings out of two hundred tests is
a very different statement from three out of four, and without the denominator the
numerator means nothing.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
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


class Insight(Base):
    __tablename__ = "insight"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )

    # A tag from `context/canonical.py` against a metric from silver or gold.
    tag: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    # 0 = the same day, 1 = the day after.
    lag: Mapped[int] = mapped_column(Integer, nullable=False)

    n_with: Mapped[int] = mapped_column(Integer, nullable=False)
    n_without: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_with: Mapped[float] = mapped_column(Float, nullable=False)
    mean_without: Mapped[float] = mapped_column(Float, nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    # Standardised, so effects on different metrics can be ranked against each other.
    effect: Mapped[float] = mapped_column(Float, nullable=False)
    p_value: Mapped[float] = mapped_column(Float, nullable=False)
    # Survived Benjamini-Hochberg across the whole family.
    significant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # How many tests were performed in the run that produced this. Without it the
    # finding cannot be read honestly.
    tested: Mapped[int] = mapped_column(Integer, nullable=False)

    # The window the analysis looked at, so a finding can be tied to its evidence.
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def direction(self) -> str:
        """Which way the tagged days went. Mirrors `Finding.direction` deliberately."""
        return "higher" if self.delta > 0 else "lower"

    __table_args__ = (
        UniqueConstraint("user_id", "tag", "metric", "lag", name="uq_insight_pair"),
        Index("ix_insight_user_significant", "user_id", "significant"),
    )
