"""The Vitals Score, stored decomposed rather than as a number.

One row in `vitals_score` is the headline. But a score nobody can interrogate is a
score nobody should trust, so every pillar and every individual contribution that went
into it is written out beside it — which is what makes the waterfall in the UI a query
rather than a recalculation, and what lets the phase-7 model explain a number without
being handed the formula and asked to do arithmetic.

`coverage` runs through all three tables for the same reason it runs through gold: a
score of 71 built from four inputs and one built from thirteen are different claims,
and only the coverage column can tell them apart. `trusted` is that judgement already
made, so a UI has one boolean to branch on rather than a threshold to re-derive.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class VitalsScore(Base):
    __tablename__ = "vitals_score"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    # coverage >= the published floor. Stored so every consumer agrees on the answer.
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", name="uq_vitals_score_day"),
        CheckConstraint("score >= 0 and score <= 100", name="score_is_out_of_100"),
        CheckConstraint("coverage >= 0 and coverage <= 1", name="coverage_is_a_fraction"),
        Index("ix_vitals_score_user_date", "user_id", "calendar_date"),
    )


class ScorePillar(Base):
    """One of the four, with the weight it carried on the day."""

    __tablename__ = "score_pillar"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    pillar: Mapped[str] = mapped_column(String(24), nullable=False)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", "pillar", name="uq_score_pillar_day"),
        CheckConstraint("score >= 0 and score <= 100", name="score_is_out_of_100"),
        Index("ix_score_pillar_user_date", "user_id", "calendar_date"),
    )


class ScoreContribution(Base):
    """One line of the waterfall: what it was, what it scored, what it was worth."""

    __tablename__ = "score_contribution"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    pillar: Mapped[str] = mapped_column(String(24), nullable=False)
    # The gold metric this line read.
    metric: Mapped[str] = mapped_column(String(48), nullable=False)

    # The underlying value, kept so the UI can show "48 bpm" next to "scored 82".
    value: Mapped[float] = mapped_column(Float, nullable=False)
    points: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    # How many points of the final score this line is responsible for. Precomputed
    # because a waterfall that makes the reader do the multiplication is not a
    # waterfall, and because the model must never do arithmetic on these.
    effect: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", "metric", name="uq_score_contribution_day"),
        CheckConstraint("points >= 0 and points <= 100", name="points_are_out_of_100"),
        Index("ix_score_contribution_user_date", "user_id", "calendar_date"),
    )
