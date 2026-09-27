"""An N-of-1 experiment: a question asked deliberately rather than noticed afterwards.

The correlation engine is observational. It looks at days that already happened and
reports what held up, which is honest and permanently limited: you drink on Fridays,
you sleep badly on Fridays, and nothing in the record can separate the two. The only
way past that is to decide in advance what will change and then change it.

That is the whole difference this table encodes. A finding has a window that was
chosen after the fact; an experiment has a window, a hypothesis and a single named
change recorded **before** the days happen. `started_at` being earlier than
`evaluated_at` is not bookkeeping — it is the property that makes the answer worth
more than the correlation engine's.

The evaluation is deliberately the same permutation test the correlation engine uses.
A new statistical procedure here would raise the question of which one to believe.
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
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base

# The lifecycle, as stored. 'running' until the window closes, then one of the rest.
PROPOSED = "proposed"
RUNNING = "running"
ANSWERED = "answered"
INCONCLUSIVE = "inconclusive"
ABANDONED = "abandoned"


class Experiment(Base):
    __tablename__ = "experiment"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )

    # The one thing being changed: a tag from `context/canonical.py`.
    tag: Mapped[str] = mapped_column(String(32), nullable=False)
    # The metric the change is expected to move, from silver or gold.
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    # Whether the effect is expected the same day or the next one.
    lag: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What is being asked, in the words shown to the person who agreed to it.
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PROPOSED)
    # Written when the experiment starts, not when it is evaluated. See the docstring.
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── the answer, once there is one ───────────────────────────────────────────
    n_with: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_without: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mean_with: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_without: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # One test, decided in advance, so there is nothing to correct for — which is the
    # other reason an experiment beats trawling the same data for whatever turns up.
    significant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # The finished sentence, written in Python.
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_experiment_user_status", "user_id", "status"),)
