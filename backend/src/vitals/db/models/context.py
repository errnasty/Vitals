"""What the person said about a day.

Separate tables from `metric_daily` on purpose, and the separation is the point
rather than tidiness: silver is what a device observed and is rebuildable from
bronze at any time, while this is the only data in the app that **cannot be
recovered if it is lost**. Nobody can re-derive last Tuesday's mood from a watch.
So it never gets dropped and rebuilt with the layers above it, and it is the one
thing an export has to carry.

`tag` is validated against `context/canonical.py` before it is written. A free-text
tag would make the column a graveyard of synonyms and the correlations meaningless.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class DayContext(Base):
    """One tag on one day. A day with nothing to say has no rows at all."""

    __tablename__ = "day_context"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    # A name from the closed vocabulary — never free text.
    tag: Mapped[str] = mapped_column(String(32), nullable=False)
    # Only alcohol uses this, and only because one drink and six are different facts.
    magnitude: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", "tag", name="uq_day_context_tag"),
        CheckConstraint("magnitude is null or magnitude >= 0", name="magnitude_is_not_negative"),
        Index("ix_day_context_user_date", "user_id", "calendar_date"),
    )


class DayNote(Base):
    """Free text, for the human. Never parsed, never correlated, never shown to a model.

    It exists because a closed vocabulary cannot hold everything and a day sometimes
    needs a sentence. Keeping it out of the analysis is deliberate: text that looks
    like data invites an app to guess at it, and a guess about someone's health is
    worse than an admission that this field is just for them.
    """

    __tablename__ = "day_note"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "calendar_date", name="uq_day_note_day"),)
