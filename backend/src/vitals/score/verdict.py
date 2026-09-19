"""One word for a score, and the coarse rating the dial draws.

Kept out of the API layer and out of the UI because phase 7's brief will describe the
same number in prose, and it must not reach for a different word than the screen is
showing. Two surfaces disagreeing about whether 64 is "balanced" or "mixed" is the
kind of small incoherence that makes an app feel untrustworthy.

The bands are a judgement, not a measurement, which is why they are four named
constants rather than a formula.
"""

from __future__ import annotations

STRONG = 80.0
BALANCED = 65.0
MIXED = 50.0


def label(score: float) -> str:
    if score >= STRONG:
        return "Strong"
    if score >= BALANCED:
        return "Balanced"
    if score >= MIXED:
        return "Mixed"
    return "Strained"


def rating(score: float) -> int:
    """The 0-3 markers under the dial: a glance-level version of the same call."""
    if score >= STRONG:
        return 3
    if score >= BALANCED:
        return 2
    if score >= MIXED:
        return 1
    return 0


def caption(score: float, *, trusted: bool) -> str:
    """What sits under the number. Says so when there is not much behind it."""
    verdict = label(score)
    return verdict if trusted else f"{verdict} · limited data"
