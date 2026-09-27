"""Assembling the facts one question needs, and nothing else.

Phase 7's digest is a fixed daily summary. A question is not fixed, so this picks
what to load — and picks it **in Python, from the question's words**, not by letting
a model decide what to fetch. Two reasons. A model choosing its own retrieval is a
model that can choose to fetch nothing and answer from memory, which on health data
is the failure that matters. And the pack this builds is simultaneously the context
the model is given *and* the set of numbers it is permitted to state, so what goes in
has to be decided by something that can be tested.

The routing is keyword matching, deliberately. It is legible, it costs nothing, and
when it is wrong the answer is a few extra facts rather than a wrong one — the
fallback when nothing matches is to include the day's core, which is what most
questions turn out to need.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.ai import retrieval
from vitals.api import format as fmt
from vitals.coach import interventions
from vitals.db.models import (
    AppUser,
    DayNote,
    Experiment,
    Insight,
    ResponseTrait,
    ScoreContribution,
    VitalsScore,
)
from vitals.insights import prose
from vitals.profile import canonical as profile_vocab
from vitals.score.pillars import PILLARS

# Which words pull in which section. Lowercased, matched as substrings, so "sleeping"
# reaches "sleep" without a stemmer.
ROUTES: dict[str, tuple[str, ...]] = {
    "score": ("score", "rating", "overall", "today", "how am i", "how did i"),
    "sleep": ("sleep", "slept", "bed", "nap", "rest", "tired", "insomnia"),
    "training": ("training", "run", "ride", "workout", "load", "hard", "easy", "race", "fitness"),
    "recovery": ("recover", "hrv", "resting heart", "rhr", "readiness", "fatigue", "form"),
    "patterns": ("pattern", "alcohol", "drink", "caffeine", "cause", "affect", "why", "correlat"),
    "similar": ("similar", "like this", "before", "last time", "compare", "ever"),
    "experiment": ("experiment", "test", "trying", "trial"),
    "profile": ("zone", "max heart", "maximum heart", "my baseline", "sleep need"),
    "coach": ("should i", "what can i", "improve", "advice", "help", "better", "fix"),
}

# Always included: a question about anything is a question about a day.
CORE = "score"

# How far back the journal reaches when it is shared at all. A fortnight: far enough
# to cover "last week", short enough that a question about today does not hand over
# a year of someone's diary.
JOURNAL_DAYS = 14


@dataclass
class Pack:
    """The facts, and the text the model is given."""

    day: date | None
    sections: list[str] = field(default_factory=list)
    # The section names that were routed to, for a test and for a log line.
    routed: tuple[str, ...] = ()

    def render(self) -> str:
        """The exact text the model sees — and the only numbers it may state."""
        return "\n\n".join(self.sections)


def route(question: str) -> tuple[str, ...]:
    """Which sections this question needs."""
    lowered = question.lower()
    hit = [name for name, words in ROUTES.items() if any(w in lowered for w in words)]
    if CORE not in hit:
        hit.append(CORE)
    return tuple(sorted(hit))


async def build(
    session: AsyncSession, *, user_id: uuid.UUID, question: str, today: date | None = None
) -> Pack:
    """Everything the question asked for, as text a model can only copy from."""
    routed = route(question)
    pack = Pack(day=None, routed=routed)

    score = await session.scalar(
        select(VitalsScore)
        .where(VitalsScore.user_id == user_id)
        .order_by(VitalsScore.calendar_date.desc())
        .limit(1)
    )
    if score is None:
        pack.sections.append("No score has been computed yet.")
        return pack

    pack.day = score.calendar_date
    pack.sections.append(await _core(session, user_id=user_id, score=score))

    if "coach" in routed:
        pack.sections.append(await _coach(session, user_id=user_id))
    if "patterns" in routed:
        pack.sections.append(await _patterns(session, user_id=user_id))
    if "similar" in routed:
        pack.sections.append(await _similar(session, user_id=user_id, day=score.calendar_date))
    if "experiment" in routed:
        pack.sections.append(await _experiment(session, user_id=user_id))
    if "profile" in routed:
        pack.sections.append(await _profile(session, user_id=user_id))

    # Last, and only with permission. See `_journal`.
    pack.sections.append(await _journal(session, user_id=user_id, end=score.calendar_date))

    pack.sections = [s for s in pack.sections if s]
    return pack


async def _core(session: AsyncSession, *, user_id: uuid.UUID, score: VitalsScore) -> str:
    rows = (
        (
            await session.execute(
                select(ScoreContribution).where(
                    ScoreContribution.user_id == user_id,
                    ScoreContribution.calendar_date == score.calendar_date,
                )
            )
        )
        .scalars()
        .all()
    )

    labels = {
        contribution.metric: (pillar.label, contribution.label)
        for pillar in PILLARS
        for contribution in pillar.contributions
    }

    lines = [
        f"DAY {score.calendar_date.isoformat()}",
        f"Vitals Score {fmt.number(score.score)} out of 100, "
        f"coverage {fmt.percent(score.coverage)}"
        f"{'' if score.trusted else ' (below the trusted threshold)'}.",
    ]
    for row in sorted(rows, key=lambda r: r.effect, reverse=True):
        pillar_label, label = labels.get(row.metric, (row.pillar, row.metric))
        lines.append(
            f"- {pillar_label} / {label}: scored {fmt.number(row.points)} of 100, "
            f"worth {fmt.number(row.effect)} points of the total, "
            f"{fmt.number(row.headroom)} still available."
        )
    return "\n".join(lines)


async def _coach(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    ranked = await interventions.rank(session, user_id=user_id)
    if not ranked:
        return "WORTH DOING: nothing has enough points riding on it to be worth changing."
    lines = ["WORTH DOING (most points available first)"]
    for item in ranked:
        lines.append(f"- {item.label}: up to {fmt.number(item.headroom)} points. {item.lever}")
        if item.evidence:
            lines.append(f"  Your own data: {item.evidence}")
    return "\n".join(lines)


async def _patterns(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    rows = (
        (
            await session.execute(
                select(Insight)
                .where(Insight.user_id == user_id, Insight.significant.is_(True))
                .order_by(Insight.p_value)
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return (
            "PATTERNS: nothing has held up in this person's own data. Either nothing "
            "was found, or too few days have been logged to test anything."
        )
    lines = [f"PATTERNS (out of {rows[0].tested} tests performed)"]
    lines.extend(
        f"- {prose.sentence(row)} ({row.n_with} days with, {row.n_without} without)" for row in rows
    )
    return "\n".join(lines)


async def _similar(session: AsyncSession, *, user_id: uuid.UUID, day: date) -> str:
    found = await retrieval.similar_days(session, user_id=user_id, target=day)
    if not found:
        return "SIMILAR DAYS: not enough history to find one."
    lines = ["SIMILAR DAYS"]
    for item in found:
        score = f", scored {item.score}" if item.score else ""
        lines.append(
            f"- {item.day.isoformat()}{score}: alike on {item.alike}; unlike on {item.unlike}."
        )
    return "\n".join(lines)


async def _experiment(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    row = await session.scalar(
        select(Experiment)
        .where(Experiment.user_id == user_id)
        .order_by(Experiment.created_at.desc())
        .limit(1)
    )
    if row is None:
        return "EXPERIMENT: none has been run."
    if row.conclusion:
        return f"EXPERIMENT ({row.status}): {row.conclusion}"
    return f"EXPERIMENT ({row.status}): {row.hypothesis}"


async def _profile(session: AsyncSession, *, user_id: uuid.UUID) -> str:
    rows = (
        (await session.execute(select(ResponseTrait).where(ResponseTrait.user_id == user_id)))
        .scalars()
        .all()
    )
    if not rows:
        return "MEASURED ANCHORS: none yet — not enough history to measure any."

    lines = ["MEASURED ANCHORS"]
    for row in sorted(rows, key=lambda r: r.trait):
        lines.append(f"- {row.trait}: {fmt.metric(row.value, row.unit)} ({row.basis})")
        if row.trait == profile_vocab.MAX_HR:
            for label, lower, upper in profile_vocab.zones(row.value):
                lines.append(f"  zone {label}: {fmt.number(lower)} to {fmt.number(upper)} bpm")
    return "\n".join(lines)


async def _journal(session: AsyncSession, *, user_id: uuid.UUID, end: date) -> str:
    """The person's own notes — **only if they have said this is allowed.**

    The Log screen promised, on the screen where the text was typed, that the note is
    "never analysed and never shown to a model". That promise is not something a
    later phase gets to withdraw quietly, so the default is off and the default
    behaviour is exactly what was promised: this returns nothing and the model never
    sees a word of it.

    When it is on, the notes are included verbatim and nothing is derived from them.
    Free text cannot be correlated — that is why the tag vocabulary is closed — so
    the only honest use for a note is as something the model may read while answering,
    which is precisely what the setting grants.
    """
    user = await session.get(AppUser, user_id)
    if user is None or not user.share_notes_with_ai:
        return ""

    rows = (
        (
            await session.execute(
                select(DayNote)
                .where(
                    DayNote.user_id == user_id,
                    DayNote.calendar_date >= end - timedelta(days=JOURNAL_DAYS),
                    DayNote.calendar_date <= end,
                )
                .order_by(DayNote.calendar_date.desc())
            )
        )
        .scalars()
        .all()
    )
    written = [row for row in rows if (row.body or "").strip()]
    if not written:
        return ""

    lines = ["THEIR OWN NOTES (their words, shared with permission; quote sparingly)"]
    lines.extend(f"- {row.calendar_date.isoformat()}: {row.body.strip()}" for row in written)
    return "\n".join(lines)


def stale(day: date | None, now: date | None = None) -> str | None:
    """A sentence when the facts are older than they look, or None.

    An answer written confidently about "today" from a week-old sync is the single
    most misleading thing this feature could do, so the staleness goes into the pack
    as a fact rather than being left for the reader to notice.
    """
    if day is None:
        return None
    today = now or datetime.now(UTC).date()
    behind = (today - day).days
    if behind <= 1:
        return None
    return f"NOTE: the most recent day with data is {behind} days ago, not today."
