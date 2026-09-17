"""Turning a physiological number into points, and being honest about which kind it is.

Two kinds of scoring, and the difference matters more than the arithmetic.

**Anchored.** Some numbers have an external reference worth deferring to: the WHO's
150 weekly activity minutes, the 7-9 hours of sleep adults are advised, the step count
where the mortality curve flattens. These score against the anchor, and the anchor is
named in the code so it can be argued with.

**Personal.** Others have no meaningful absolute scale. A chronic training load of 80
is excellent for one person and a deload for another; a VO2max of 45 means nothing
without an age. These score as a percentile against that individual's own recent
history — which is also the only honest answer to "is this good?" when the only
comparison available is you.

Nothing here knows about pillars, databases or dates. A curve is a float in and a
float out, so the calibration is arguable on its own terms.
"""

from __future__ import annotations

from collections.abc import Sequence

MIN = 0.0
MAX = 100.0


def ramp(value: float, *, zero_at: float, hundred_at: float) -> float:
    """Linear between two named points, clamped outside them.

    Works in either direction: `zero_at` above `hundred_at` scores lower-is-better
    (resting heart rate, sleep debt), and below it scores higher-is-better (steps,
    activity minutes). Naming both ends rather than a midpoint and a slope means the
    calibration reads as a claim someone can disagree with.
    """
    if zero_at == hundred_at:
        raise ValueError("a ramp needs two distinct points")
    fraction = (value - zero_at) / (hundred_at - zero_at)
    return max(MIN, min(MAX, fraction * MAX))


def band(value: float, *, low: float, high: float, margin: float) -> float:
    """Full marks inside a range, falling away over `margin` on either side.

    For quantities where both too little and too much are worse than the middle —
    acute:chronic workload being the one this was written for.
    """
    if low > high:
        raise ValueError("band low must not exceed high")
    if margin <= 0:
        raise ValueError("band margin must be positive")
    if low <= value <= high:
        return MAX
    distance = low - value if value < low else value - high
    return max(MIN, MAX * (1.0 - distance / margin))


def percentile(value: float, history: Sequence[float]) -> float | None:
    """Where `value` sits in this person's own recent distribution, as 0-100.

    Ties count as half, so a metric that barely moves scores near the middle rather
    than at an extreme decided by a rounding error. Returns None below a usable amount
    of history — a percentile against four observations is a number with no content,
    and the layer above turns that into missing coverage rather than a guess.
    """
    if len(history) < MIN_HISTORY:
        return None
    below = sum(1 for past in history if past < value)
    equal = sum(1 for past in history if past == value)
    return MAX * (below + equal / 2) / len(history)


# Below this, a personal percentile says more about the sample than the person.
MIN_HISTORY = 20
