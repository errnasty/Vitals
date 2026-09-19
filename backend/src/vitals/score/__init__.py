"""Phase 5: the Vitals Score.

One number a day, composed from four pillars, every one of them decomposed down to the
individual readings that moved it. The composition is pure and the calibration lives in
one readable file, so the score is arguable rather than oracular.

Two commitments run through the package. **Coverage is weight**: an input nobody has
data for drags its pillar down instead of quietly redistributing itself, and a score
below the published trust floor is flagged rather than dressed up. And **the effects
sum to the score**: a contribution's `effect` is the points of the final number it is
responsible for, computed here, so nothing downstream — the UI or the model — ever has
to do arithmetic to explain it.
"""

from vitals.score.compose import (
    MIN_CONTRIBUTION_COVERAGE,
    MIN_TRUSTED_COVERAGE,
    ContributionResult,
    DayScore,
    Gold,
    PillarResult,
    Reading,
    compose,
)
from vitals.score.engine import SCORED_METRICS, ScoreResult, gold_span, score
from vitals.score.pillars import PILLARS, Contribution, Pillar

__all__ = [
    "MIN_CONTRIBUTION_COVERAGE",
    "MIN_TRUSTED_COVERAGE",
    "PILLARS",
    "Contribution",
    "ContributionResult",
    "DayScore",
    "Gold",
    "Pillar",
    "PillarResult",
    "Reading",
    "SCORED_METRICS",
    "ScoreResult",
    "compose",
    "gold_span",
    "score",
]
