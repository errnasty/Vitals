"""The daily brief, stored with everything needed to distrust it.

A row here is prose, which makes it the least verifiable thing in the database — so it
carries its provenance beside it. `source` says whether a model wrote it or Python
composed it; `grounded` says whether every number in it was checked against the digest;
`digest_fingerprint` says which day's facts it was written from.

That last column is also the cost control. The brief is regenerated only when the
fingerprint changes, so re-running `vitals brief` after a sync that changed nothing is
free. At one brief a day the difference is small; at a backfill that recomputes a year
of scores it is the difference between a few cents and a few hundred calls.

`attempts` records how many tries the grounding validator rejected. A row that reads
`source='python', attempts=2` is the system working: the model could not stay grounded,
so the reader got Python's version instead of a plausible-sounding invention.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base

# Who wrote the words.
SOURCE_MODEL = "model"
SOURCE_PYTHON = "python"


class DailyBrief(Base):
    __tablename__ = "daily_brief"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False)

    body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # The OpenRouter slug that actually served it, which is not always the one asked
    # for — OpenRouter routes around a provider that is down.
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Content hash of the rendered digest. Same hash, same brief, no second call.
    digest_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "calendar_date", name="uq_daily_brief_day"),
        CheckConstraint("source in ('model', 'python')", name="source_is_known"),
        Index("ix_daily_brief_user_date", "user_id", "calendar_date"),
    )
