"""Body composition: the trend, because the daily number is mostly noise.

Day-to-day scale weight moves by more than a week of real change — hydration, glycogen,
what you ate last night. Reporting it raw invites reacting to noise, so what this
module publishes is a smoothed trend and the slope of it, and the raw value stays in
silver for anyone who wants it.
"""

from __future__ import annotations

from datetime import date

from vitals.analytics import canonical as d
from vitals.analytics.math import ewma, slope
from vitals.analytics.model import Derived
from vitals.analytics.series import Inputs
from vitals.normalize import canonical as silver

# Roughly the Hacker's Diet smoothing: slow enough to ignore a salty dinner, fast
# enough to show a fortnight's real direction.
WEIGHT_TAU_DAYS = 10.0
FAT_TAU_DAYS = 14.0
SLOPE_DAYS = 30
DAYS_PER_WEEK = 7


def compute(inputs: Inputs, day: date) -> list[Derived]:
    out: list[Derived] = []
    out.extend(_trend(inputs, day, silver.WEIGHT, d.WEIGHT_TREND, WEIGHT_TAU_DAYS))
    out.extend(_trend(inputs, day, silver.BODY_FAT_PCT, d.BODY_FAT_TREND, FAT_TAU_DAYS))

    weight = inputs.get(silver.WEIGHT)
    window = weight.window(day, SLOPE_DAYS)
    observed = sum(1 for value in window if value is not None)
    if observed >= 2:
        per_day = slope(window)
        if per_day is not None:
            out.append(
                Derived(
                    metric=d.WEIGHT_SLOPE,
                    calendar_date=day,
                    value=per_day * DAYS_PER_WEEK,
                    inputs=observed,
                )
            )
    return out


def _trend(inputs: Inputs, day: date, source: str, metric: str, tau: float) -> list[Derived]:
    series = inputs.get(source)
    window = series.window(day, SLOPE_DAYS)
    observed = sum(1 for value in window if value is not None)
    if observed == 0:
        return []

    # The whole loaded history feeds the average, so the trend does not restart at the
    # edge of the window being written.
    smoothed = ewma(series.values[: (series.index(day) or 0) + 1], time_constant_days=tau)[-1]
    if smoothed is None:
        return []
    return [Derived(metric=metric, calendar_date=day, value=smoothed, inputs=observed)]
