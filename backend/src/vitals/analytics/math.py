"""The numeric primitives every analytics module is built from.

Pure functions over plain floats: no database, no dates, no domain. That is what
makes the sports science above them checkable — an exponentially weighted average is
either right or wrong on its own terms, and you can say which without a fixture.

Every function here returns `None` rather than guessing when it has too little to work
with. A fitness number computed from four days of data is not a small error, it is a
confident lie, and the layer above turns that `None` into honest missing coverage.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def smoothing_factor(time_constant_days: float) -> float:
    """The α of an exponentially weighted average with a given time constant.

    `1 - exp(-1/τ)` rather than the `1/τ` the training-load literature often writes.
    They differ by under 2% at τ=42 and the exponential form is the one that actually
    decays with the half-life it claims, which matters when the same helper is used
    for a 7-day and a 90-day constant.
    """
    if time_constant_days <= 0:
        raise ValueError("time constant must be positive")
    return 1.0 - math.exp(-1.0 / time_constant_days)


def ewma(values: Sequence[float | None], *, time_constant_days: float) -> list[float | None]:
    """Exponentially weighted moving average, carried across gaps.

    A `None` is a day with no observation, not a zero: the average holds its previous
    value through the gap instead of decaying towards nothing. Decaying would mean a
    fortnight without a weigh-in reads as weight loss.

    Callers that mean "nothing happened here" — a rest day carries genuinely zero
    training load — pass `0.0` and get the decay they want.
    """
    alpha = smoothing_factor(time_constant_days)
    out: list[float | None] = []
    current: float | None = None
    for value in values:
        if value is not None:
            current = value if current is None else current + alpha * (value - current)
        out.append(current)
    return out


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def stdev(values: Sequence[float]) -> float | None:
    """Sample standard deviation. Needs two points; one point has no spread."""
    if len(values) < 2:
        return None
    average = sum(values) / len(values)
    variance = sum((v - average) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def zscore(value: float, baseline: float, deviation: float | None) -> float | None:
    """How unusual today is, in standard deviations of this person's own history.

    Population norms are useless for HRV — an individual's own spread is the only
    meaningful scale. A flat baseline (zero spread) yields None rather than dividing
    by zero and reporting infinite surprise.
    """
    if deviation is None or deviation <= 0:
        return None
    return (value - baseline) / deviation


def slope(values: Sequence[float | None]) -> float | None:
    """Least-squares slope per step, over the points that exist.

    Gaps are skipped rather than interpolated, and the x used is each value's real
    position — so a month of weights with a fortnight missing in the middle reports
    the trend across the whole month, not across the nine days that happen to have
    readings.
    """
    points = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(points) < 2:
        return None

    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    return numerator / denominator


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


MINUTES_PER_DAY = 1440


def circular_stdev_minutes(minutes: Sequence[float]) -> float | None:
    """Standard deviation of times of day, in minutes, respecting the wrap at midnight.

    Ordinary spread is wrong here and wrong in the worst direction: someone who sleeps
    at 23:50 one night and 00:10 the next is twenty minutes apart, but arithmetic puts
    them 1420 apart and reports a wildly inconsistent sleeper. So the times become
    angles, and the spread is the angular one.
    """
    if len(minutes) < 2:
        return None

    angles = [2 * math.pi * (value % MINUTES_PER_DAY) / MINUTES_PER_DAY for value in minutes]
    cos_mean = sum(math.cos(a) for a in angles) / len(angles)
    sin_mean = sum(math.sin(a) for a in angles) / len(angles)
    resultant = math.hypot(cos_mean, sin_mean)
    if resultant <= 0:
        # Perfectly opposed times: maximally inconsistent, and -2·ln(0) is undefined.
        return None

    # max(): identical times give log(1)=0, whose sqrt is a negative zero.
    angular = math.sqrt(max(0.0, -2.0 * math.log(resultant)))
    return angular * MINUTES_PER_DAY / (2 * math.pi)
