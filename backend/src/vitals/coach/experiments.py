"""Proposing an experiment, running it, and answering it.

Three operations, and the order matters more than any of them. `propose` writes down
what will change and what it is expected to move **before** the days happen; `start`
opens the window; `evaluate` runs one pre-declared test when the window closes. A
question asked in that order beats the same question asked of the same data
afterwards, and it is the only way this app can get past "you drink on Fridays and
sleep badly on Fridays".

The test is the same permutation test the correlation engine uses, with one
difference: there is nothing to correct for. The engine runs a few hundred tests and
must divide by all of them; an experiment runs exactly one, declared in advance. That
is why an experiment can reach a conclusion on a sample the engine would refuse.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.context import canonical as tags
from vitals.context import store as context_store
from vitals.db.models import (
    ABANDONED,
    ANSWERED,
    INCONCLUSIVE,
    PROPOSED,
    RUNNING,
    DerivedDaily,
    Experiment,
    MetricDaily,
)
from vitals.insights.analysis import MIN_GROUP, SEED, Observation, observations_for, test_one
from vitals.insights.prose import PHRASE, unit_for
from vitals.logging import get_logger

log = get_logger(__name__)

# Long enough for both arms to reach the group floor without a perfect split, short
# enough that someone will actually finish it. Two weeks of changing one thing is a
# commitment; six is a lifestyle, and an experiment nobody completes answers nothing.
DEFAULT_DAYS = 21

# One test, declared in advance, so this is the conventional threshold rather than a
# corrected one. The correlation engine's 0.10 false-discovery rate is the right
# setting for a few hundred simultaneous questions; it is the wrong one for a single
# question someone spent three weeks answering.
ALPHA = 0.05

# How much of the window has to carry a decision either way. A three-week experiment
# with four tagged days did not happen, and reporting a null result from it would be
# reporting that the person forgot rather than that the change did nothing.
MIN_LOGGED_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class Proposal:
    tag: str
    metric: str
    lag: int
    hypothesis: str
    days: int


def _phrase(metric: str) -> str:
    return PHRASE.get(metric, metric)


def propose(*, tag: str, metric: str, lag: int = 1, days: int = DEFAULT_DAYS) -> Proposal:
    """Write down the question before the days happen."""
    label = tags.BY_NAME[tag].reads_as() if tag in tags.BY_NAME else tag
    when = "the next day" if lag else "the same day"
    return Proposal(
        tag=tag,
        metric=metric,
        lag=lag,
        hypothesis=(
            f"Over the next {days} days, log {label} honestly every day. "
            f"The question is whether {_phrase(metric)} differs on {when} — "
            "and the answer is written before the days start, so it cannot be "
            "chosen afterwards to fit what happened."
        ),
        days=days,
    )


async def start(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    proposal: Proposal,
    today: date | None = None,
) -> Experiment:
    """Open the window. Only one experiment runs at a time, on purpose.

    Two changes at once, and neither answer means anything — which is the entire
    reason for running an experiment rather than reading a correlation.
    """
    begin = today or datetime.now(UTC).date()

    running = await session.scalar(
        select(Experiment).where(
            Experiment.user_id == user_id, Experiment.status.in_([PROPOSED, RUNNING])
        )
    )
    if running is not None:
        running.status = ABANDONED
        log.info("experiment.superseded", experiment=str(running.id))

    row = Experiment(
        user_id=user_id,
        tag=proposal.tag,
        metric=proposal.metric,
        lag=proposal.lag,
        hypothesis=proposal.hypothesis,
        status=RUNNING,
        started_on=begin,
        ends_on=begin + timedelta(days=proposal.days - 1),
    )
    session.add(row)
    await session.commit()
    log.info("experiment.started", tag=proposal.tag, metric=proposal.metric, days=proposal.days)
    return row


async def active(session: AsyncSession, *, user_id: uuid.UUID) -> Experiment | None:
    row: Experiment | None = await session.scalar(
        select(Experiment).where(
            Experiment.user_id == user_id, Experiment.status.in_([PROPOSED, RUNNING])
        )
    )
    return row


async def _series(
    session: AsyncSession, *, user_id: uuid.UUID, metric: str, start_day: date, end_day: date
) -> dict[date, float]:
    for model in (MetricDaily, DerivedDaily):
        rows = (
            await session.execute(
                select(model.calendar_date, model.value).where(
                    model.user_id == user_id,
                    model.metric == metric,
                    model.calendar_date >= start_day,
                    model.calendar_date <= end_day,
                )
            )
        ).all()
        if rows:
            return {day: float(value) for day, value in rows}
    return {}


async def evaluate(
    session: AsyncSession, *, user_id: uuid.UUID, today: date | None = None
) -> Experiment | None:
    """Answer the running experiment, if its window has closed.

    Returns the experiment when it reached a verdict of any kind — including
    "inconclusive", which is a real answer and the most likely one.
    """
    now = today or datetime.now(UTC).date()
    row = await active(session, user_id=user_id)
    if row is None or row.ends_on is None or row.started_on is None or now <= row.ends_on:
        return None

    # The window is the experiment's own, plus one day when the effect is expected
    # the next morning — otherwise the final day's change has nowhere to show up.
    window_end = row.ends_on + timedelta(days=row.lag)
    tagged_days = await context_store.span(
        session, user_id=user_id, start=row.started_on, end=window_end
    )
    logged = {day for day, names in tagged_days.items() if names}

    span = (row.ends_on - row.started_on).days + 1
    if len(tagged_days) < span * MIN_LOGGED_FRACTION:
        row.status = INCONCLUSIVE
        row.conclusion = (
            f"Only {len(tagged_days)} of {span} days were logged, which is too few to "
            "compare. This says the experiment did not happen, not that the change "
            "does nothing."
        )
        row.evaluated_at = datetime.now(UTC)
        await session.commit()
        return row

    series = await _series(
        session,
        user_id=user_id,
        metric=row.metric,
        start_day=row.started_on,
        end_day=window_end,
    )
    on_days = {day for day in logged if row.tag in tagged_days.get(day, set())}

    observations: list[Observation] = observations_for(
        tagged_days=on_days, series=series, lag=row.lag
    )
    finding = test_one(
        observations,
        tag=row.tag,
        metric=row.metric,
        lag=row.lag,
        rng=random.Random(SEED),
    )

    row.evaluated_at = datetime.now(UTC)

    if finding is None:
        row.status = INCONCLUSIVE
        row.conclusion = (
            f"The days did not split far enough apart to compare — this needs at "
            f"least {MIN_GROUP} days on each side, and one side did not reach it."
        )
        await session.commit()
        return row

    row.n_with = finding.n_with
    row.n_without = finding.n_without
    row.mean_with = finding.mean_with
    row.mean_without = finding.mean_without
    row.delta = finding.delta
    row.effect = finding.effect
    row.p_value = finding.p_value
    row.significant = finding.p_value <= ALPHA
    row.status = ANSWERED if row.significant else INCONCLUSIVE
    row.conclusion = _conclusion(row, finding.direction)

    await session.commit()
    log.info(
        "experiment.evaluated",
        status=row.status,
        p_value=round(finding.p_value, 4),
        n_with=finding.n_with,
        n_without=finding.n_without,
    )
    return row


def _conclusion(row: Experiment, direction: str) -> str:
    """The answer as one sentence, numbers included, written here.

    The null result gets the longer sentence deliberately. "Nothing found" is the
    most likely outcome of any honest experiment, and left as two words it reads like
    a failure rather than the information it is.
    """
    label = tags.BY_NAME[row.tag].reads_as() if row.tag in tags.BY_NAME else row.tag
    phrase = _phrase(row.metric)
    unit = unit_for(row.metric)
    gap = abs(row.delta or 0.0)

    if row.significant:
        return (
            f"Over {(row.n_with or 0) + (row.n_without or 0)} days, {phrase} differed by "
            f"{gap:.1f} {unit} on days with {label} — a gap this size came up by chance "
            f"in fewer than {ALPHA:.0%} of the shuffles. That is your own result, from "
            "a question asked before the days happened."
        )
    return (
        f"Over {(row.n_with or 0) + (row.n_without or 0)} days, {phrase} differed by "
        f"{gap:.1f} {unit} on days with {label}, which is well inside what chance "
        "produces on its own. Either it does not move this for you, or the effect is "
        "smaller than three weeks can see. Both are worth knowing, and neither is a "
        "reason to keep worrying about it."
    )
