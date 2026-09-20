"""Composing the four pillars into one number, and keeping the receipts.

Pure: gold readings in, a decomposed score out. No database, no clock. The arithmetic
is deliberately simple — weighted means, twice — because the interesting decisions all
live in `pillars.py` and a composition step nobody can follow would hide them.

The property that makes the waterfall honest: **every contribution's `effect` is the
points of the final score it is responsible for, and they sum to the score.** Not a
rough attribution, not a share of a pillar — the actual decomposition. A UI can render
it as a waterfall without arithmetic, and the phase-7 model can say "your sleep debt
cost you four points" because Python already worked out that it was four.

Coverage is applied as weight, not as a footnote. A contribution nobody has data for
does not quietly redistribute its weight to the others as if it had never been
intended; it drags the pillar's coverage down, and the score says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from vitals.analytics.math import clamp
from vitals.score.pillars import PILLARS, Contribution, Pillar, history_days

# Below this, one reading is too thin to let into the score at all.
MIN_CONTRIBUTION_COVERAGE = 0.25
# Below this, the score is still computed and stored, but flagged as untrusted. It is
# a published constant so the UI, the API and the phase-7 prompt all agree.
MIN_TRUSTED_COVERAGE = 0.5


@dataclass(frozen=True, slots=True)
class Reading:
    value: float
    coverage: float


@dataclass(frozen=True, slots=True)
class Gold:
    """Everything the score reads, indexed for it."""

    readings: dict[tuple[str, date], Reading]

    def at(self, metric: str, day: date) -> Reading | None:
        return self.readings.get((metric, day))

    def history(self, metric: str, day: date, days: int) -> list[float]:
        """Values for this metric in the `days` before `day`, excluding the day itself.

        Excluding today is what stops a percentile grading a value against a
        distribution it is already part of — the same reason recovery's baseline ends
        yesterday.
        """
        out = []
        for offset in range(1, days + 1):
            reading = self.readings.get((metric, day - timedelta(days=offset)))
            if reading is not None:
                out.append(reading.value)
        return out


@dataclass(frozen=True, slots=True)
class ContributionResult:
    pillar: str
    metric: str
    label: str
    value: float
    points: float
    weight: float
    coverage: float
    effect: float
    # Points of the final score this line would add if it scored 100 from here.
    # Computed where the weighting factor is already in hand, for the same reason
    # `effect` is: a screen that answers "what would help most" by multiplying
    # weights itself is a screen doing arithmetic, and a second place for that
    # arithmetic to be wrong.
    headroom: float
    rationale: str


@dataclass(frozen=True, slots=True)
class PillarResult:
    name: str
    label: str
    score: float
    coverage: float
    weight: float
    contributions: tuple[ContributionResult, ...]


@dataclass(frozen=True, slots=True)
class DayScore:
    calendar_date: date
    score: float
    coverage: float
    trusted: bool
    pillars: tuple[PillarResult, ...]

    @property
    def contributions(self) -> list[ContributionResult]:
        return [c for pillar in self.pillars for c in pillar.contributions]


# The top of the points scale, named so the headroom calculation reads as "what is
# left" rather than as a magic 100.
MAX_POINTS = 100.0


def _factor(scored: _Scored, covered: float, share: float) -> float:
    """How many points of the final score one point of this line is worth."""
    return (scored.contribution.weight * scored.coverage / covered) * share


@dataclass(frozen=True, slots=True)
class _Scored:
    contribution: Contribution
    value: float
    points: float
    coverage: float


def _score_contribution(gold: Gold, day: date, contribution: Contribution) -> _Scored | None:
    reading = gold.at(contribution.metric, day)
    if reading is None or reading.coverage < MIN_CONTRIBUTION_COVERAGE:
        return None

    history = gold.history(contribution.metric, day, history_days(contribution.scorer))
    points = contribution.scorer(reading.value, history)
    if points is None:
        # A personal percentile with too little history. Not an error — it simply
        # cannot be scored honestly yet, and counts as uncovered rather than zero.
        return None

    return _Scored(
        contribution=contribution,
        value=reading.value,
        points=points,
        coverage=reading.coverage,
    )


def _score_pillar(gold: Gold, day: date, pillar: Pillar) -> tuple[list[_Scored], float, float]:
    """Returns the scored contributions, the pillar score, and its coverage."""
    scored = [
        result
        for result in (_score_contribution(gold, day, c) for c in pillar.contributions)
        if result is not None
    ]

    # Coverage is measured against everything the pillar *intends* to use, so a
    # missing input lowers it rather than silently promoting the others.
    intended = sum(c.weight for c in pillar.contributions)
    covered = sum(s.contribution.weight * s.coverage for s in scored)
    coverage = covered / intended if intended else 0.0

    if not scored or covered <= 0:
        return scored, 0.0, coverage

    # A weighted mean of values that are all in [0, 100] is mathematically in [0, 100],
    # but with awkward coverage weights it can land on 100.00000000000001 — which is a
    # check-constraint violation rather than a rounding curiosity.
    score = sum(s.points * s.contribution.weight * s.coverage for s in scored) / covered
    return scored, clamp(score, 0.0, 100.0), coverage


def compose(gold: Gold, day: date, pillars: tuple[Pillar, ...] = PILLARS) -> DayScore | None:
    """The whole score for one day, or None when nothing can be said about it."""
    parts: list[tuple[Pillar, list[_Scored], float, float]] = []
    for pillar in pillars:
        scored, score, coverage = _score_pillar(gold, day, pillar)
        parts.append((pillar, scored, score, coverage))

    weighted_coverage = sum(pillar.weight * coverage for pillar, _, _, coverage in parts)
    if weighted_coverage <= 0:
        return None

    intended = sum(pillar.weight for pillar in pillars)
    total = clamp(
        sum(score * pillar.weight * coverage for pillar, _, score, coverage in parts)
        / weighted_coverage,
        0.0,
        100.0,
    )
    total_coverage = weighted_coverage / intended if intended else 0.0

    results = []
    for pillar, scored, score, coverage in parts:
        # This pillar's share of the final number, so that the contribution effects
        # below it sum to exactly the points it put on the board.
        share = (pillar.weight * coverage) / weighted_coverage
        covered = sum(s.contribution.weight * s.coverage for s in scored)

        contributions = tuple(
            ContributionResult(
                pillar=pillar.name,
                metric=s.contribution.metric,
                label=s.contribution.label,
                value=s.value,
                points=s.points,
                weight=s.contribution.weight,
                coverage=s.coverage,
                effect=s.points * _factor(s, covered, share),
                headroom=(MAX_POINTS - s.points) * _factor(s, covered, share),
                rationale=s.contribution.rationale,
            )
            for s in scored
            if covered > 0
        )
        results.append(
            PillarResult(
                name=pillar.name,
                label=pillar.label,
                score=score,
                coverage=coverage,
                weight=pillar.weight,
                contributions=contributions,
            )
        )

    return DayScore(
        calendar_date=day,
        score=total,
        coverage=total_coverage,
        trusted=total_coverage >= MIN_TRUSTED_COVERAGE,
        pillars=tuple(results),
    )
