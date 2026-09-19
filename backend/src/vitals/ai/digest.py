"""The compact digest: everything the model is allowed to know about a day.

This is the boundary the architecture diagram draws between gold and AI, and it is a
narrow one on purpose. The model never sees a timeseries — it sees one day's score,
already decomposed, with every number **already formatted by Python**. There is
nothing here it could be tempted to do arithmetic on, because there is no arithmetic
left to do: the effects were multiplied out in `score/compose.py`, the deltas were
subtracted here, and both arrived as strings.

That is also what makes the grounding check in `grounding.py` possible. The digest is
rendered to text exactly once, and that text is simultaneously what the model reads
and the set of numbers it is permitted to say. The two cannot drift apart because they
are the same string.

**Weight and body composition are deliberately absent.** `score/pillars.py` refuses to
score them because there is no direction that is right without knowing someone's goal,
and a daily note that mentions them is a verdict whatever words it reaches for. Leaving
them out of the digest is the only reliable way to keep an LLM from commenting on them
— a prompt asking it not to is a request, and this is a guarantee.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.ai.signals import Signal, detect
from vitals.analytics import canonical as gold
from vitals.api import format as fmt
from vitals.db.models import DerivedDaily, ScoreContribution, ScorePillar, VitalsScore
from vitals.score import verdict
from vitals.score.pillars import BY_NAME

# Days of score history the digest summarises into a single comparison. Two weeks is
# long enough for "quieter than usual" to mean something and short enough that a month
# of gradual drift does not swamp it.
COMPARISON_DAYS = 14
# Contributions are ranked by effect and truncated: the tail of a waterfall is noise
# to a two-sentence note, and every line costs tokens on a call that runs daily.
MAX_CONTRIBUTIONS = 8


@dataclass(frozen=True, slots=True)
class ScoreLine:
    value: int
    display: str
    verdict: str
    coverage: str
    trusted: bool


@dataclass(frozen=True, slots=True)
class PillarLine:
    name: str
    label: str
    display: str
    coverage: str


@dataclass(frozen=True, slots=True)
class ContributionLine:
    label: str
    pillar: str
    # The underlying reading, formatted the way its unit wants to be read.
    value: str
    points: str
    # Points of the final score this line is responsible for, signed against the
    # average line so "carried" and "cost" are Python's judgement rather than the
    # model's.
    effect: str
    rationale: str


@dataclass(frozen=True, slots=True)
class Comparison:
    """Where the day sits against the fortnight behind it."""

    days: int
    mean: str
    delta: str
    direction: str


@dataclass(frozen=True, slots=True)
class Digest:
    calendar_date: date
    score: ScoreLine
    pillars: tuple[PillarLine, ...]
    contributions: tuple[ContributionLine, ...]
    comparison: Comparison | None
    signals: tuple[Signal, ...]

    def render(self) -> str:
        """The exact text the model is shown — and the exact set of numbers it may say.

        Rendered once and reused for both purposes. A second renderer for the
        validator would be a second chance to disagree with this one.
        """
        lines = [
            f"DATE: {self.calendar_date.isoformat()}",
            f"SCORE: {self.score.display} out of 100 — {self.score.verdict}",
            f"COVERAGE: {self.score.coverage}"
            + ("" if self.score.trusted else " (below the trusted floor)"),
        ]
        if self.comparison is not None:
            lines.append(
                f"VERSUS THE LAST {self.comparison.days} DAYS: "
                f"mean {self.comparison.mean}, and today is {self.comparison.delta}"
            )

        lines.append("")
        lines.append("PILLARS (out of 100, with the share of its inputs present):")
        for pillar in self.pillars:
            lines.append(f"- {pillar.label}: {pillar.display} (coverage {pillar.coverage})")

        lines.append("")
        lines.append(
            "WHAT MOVED THE SCORE (effect = points of the final score this line put on "
            "the board; they sum to the score):"
        )
        for line in self.contributions:
            lines.append(
                f"- {line.label} [{line.pillar}]: {line.value}, scored {line.points}, "
                f"effect {line.effect} — {line.rationale}"
            )

        lines.append("")
        if self.signals:
            lines.append("WHAT PYTHON NOTICED (ranked; nothing else is worth raising):")
            for signal in self.signals:
                lines.append(f"- {signal.sentence}")
        else:
            lines.append("WHAT PYTHON NOTICED: nothing worth raising. This is an ordinary day.")

        return "\n".join(lines)

    @property
    def fingerprint(self) -> str:
        """Stable identity for the rendered digest.

        A daily brief is regenerated only when this changes, which is what keeps a
        re-run of `vitals brief` from being a paid call. It is a content hash rather
        than a timestamp because recomputing gold over an unchanged day should not
        count as the day having changed.
        """
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()[:32]


# Units a bare number cannot carry. A waterfall has a column header to explain what
# `0.05` means; a sentence does not, and a model handed `0.05` for a heart-rate
# variability line has every reason to write that the HRV was 0.05.
UNIT_SUFFIX = {"sd": "SD from your own baseline", "au": "load units"}


def _reading(value: float, unit: str) -> str:
    """One contribution's underlying value, readable without the column it came from."""
    if unit == "sd":
        # A z-score is a direction as much as a magnitude, so it keeps its sign.
        return f"{fmt.signed(value, places=2)} {UNIT_SUFFIX[unit]}"
    suffix = UNIT_SUFFIX.get(unit)
    text = fmt.metric(value, unit)
    return f"{text} {suffix}" if suffix else text


def _effect(value: float) -> str:
    """Unsigned: every line puts points *on* the board, and they sum to the score.

    A signed rendering would imply some lines subtract, which is not what the
    decomposition means — a weak line contributes few points, not negative ones.
    """
    return f"{fmt.number(value, places=1)} pts"


async def load(
    session: AsyncSession, *, user_id: uuid.UUID, day: date | None = None
) -> Digest | None:
    """Assemble the digest for one day, or None when that day has no score."""
    statement = select(VitalsScore).where(VitalsScore.user_id == user_id)
    if day is not None:
        statement = statement.where(VitalsScore.calendar_date == day)
    row: VitalsScore | None = await session.scalar(
        statement.order_by(VitalsScore.calendar_date.desc()).limit(1)
    )
    if row is None:
        return None

    on = row.calendar_date

    pillar_rows = (
        (
            await session.execute(
                select(ScorePillar)
                .where(ScorePillar.user_id == user_id, ScorePillar.calendar_date == on)
                .order_by(ScorePillar.weight.desc())
            )
        )
        .scalars()
        .all()
    )
    contribution_rows = (
        (
            await session.execute(
                select(ScoreContribution).where(
                    ScoreContribution.user_id == user_id, ScoreContribution.calendar_date == on
                )
            )
        )
        .scalars()
        .all()
    )
    # The prior fortnight, excluding today: a day compared against a mean it is part of
    # is compared against itself.
    history = list(
        (
            await session.execute(
                select(VitalsScore.score)
                .where(
                    VitalsScore.user_id == user_id,
                    VitalsScore.calendar_date >= on - timedelta(days=COMPARISON_DAYS),
                    VitalsScore.calendar_date < on,
                )
                .order_by(VitalsScore.calendar_date)
            )
        )
        .scalars()
        .all()
    )
    # Gold readings the signals need but the score does not contribute from.
    context: dict[str, float] = {
        metric: value
        for metric, value in (
            await session.execute(
                select(DerivedDaily.metric, DerivedDaily.value).where(
                    DerivedDaily.user_id == user_id,
                    DerivedDaily.calendar_date == on,
                    DerivedDaily.metric.in_(signal_metrics()),
                )
            )
        ).all()
    }

    return build(row, pillar_rows, contribution_rows, history=history, context=context)


def signal_metrics() -> tuple[str, ...]:
    """Gold metrics the signal rules read directly."""
    return (gold.ACWR, gold.MONOTONY, gold.SLEEP_DEBT, gold.TSB)


def build(
    row: VitalsScore,
    pillars: Sequence[ScorePillar],
    contributions: Sequence[ScoreContribution],
    *,
    history: Sequence[float],
    context: dict[str, float],
) -> Digest:
    """Pure: rows in, a finished digest out. No session, no clock."""
    score = ScoreLine(
        value=round(row.score),
        display=fmt.score(row.score),
        verdict=verdict.label(row.score),
        coverage=fmt.percent(row.coverage),
        trusted=row.trusted,
    )

    pillar_lines = tuple(
        PillarLine(
            name=pillar.pillar,
            label=BY_NAME[pillar.pillar].label if pillar.pillar in BY_NAME else pillar.pillar,
            display=fmt.score(pillar.score),
            coverage=fmt.percent(pillar.coverage),
        )
        for pillar in pillars
    )

    by_metric = {c.metric: c for pillar in BY_NAME.values() for c in pillar.contributions}
    ranked = sorted(contributions, key=lambda c: c.effect, reverse=True)[:MAX_CONTRIBUTIONS]
    contribution_lines = tuple(
        ContributionLine(
            label=by_metric[item.metric].label if item.metric in by_metric else item.metric,
            pillar=item.pillar,
            value=_reading(item.value, gold.unit_for(item.metric)),
            points=fmt.score(item.points),
            effect=_effect(item.effect),
            rationale=by_metric[item.metric].rationale if item.metric in by_metric else "",
        )
        for item in ranked
    )

    comparison = None
    if history:
        mean = sum(history) / len(history)
        delta = row.score - mean
        # A fortnight of scores is noisy; a point either way is not news, and saying
        # so in words rather than a signed number is what stops the model deciding
        # for itself whether −2 is a fall or a wobble.
        direction = fmt.direction(delta, tolerance=1.0)
        if direction == "flat":
            delta_text = "level with it"
        else:
            delta_text = (
                f"{fmt.number(abs(delta), places=0)} {'above' if direction == 'up' else 'below'} it"
            )
        comparison = Comparison(
            days=len(history), mean=fmt.score(mean), delta=delta_text, direction=direction
        )

    return Digest(
        calendar_date=row.calendar_date,
        score=score,
        pillars=pillar_lines,
        contributions=contribution_lines,
        comparison=comparison,
        signals=detect(
            score=row.score,
            coverage=row.coverage,
            trusted=row.trusted,
            pillars=pillars,
            contributions=contributions,
            history=history,
            context=context,
        ),
    )
