"""Longevity: the handful of numbers with the strongest all-cause mortality evidence.

Cardiorespiratory fitness is the headline. Across large cohorts VO2max separates
outcomes more sharply than smoking status, and unlike most risk factors it is directly
trainable — which makes its *trend* the single most useful number this app computes.

Weekly activity minutes are counted the way the WHO counts them: 150 minutes of
moderate activity a week, with vigorous minutes worth double. Steps are kept because
the dose-response is real, and because it is the number people actually act on.
"""

from __future__ import annotations

from datetime import date

from vitals.analytics import canonical as d
from vitals.analytics.math import ewma, mean, slope
from vitals.analytics.model import Derived
from vitals.analytics.series import Inputs
from vitals.normalize import canonical as silver

VO2MAX_TAU_DAYS = 30.0
VO2MAX_SLOPE_DAYS = 90
DAYS_PER_YEAR = 365
WEEK = 7

# WHO: 150 minutes of moderate-intensity activity per week, vigorous counting double.
WEEKLY_GUIDELINE_MINUTES = 150.0
VIGOROUS_MULTIPLIER = 2.0


def compute(inputs: Inputs, day: date) -> list[Derived]:
    out: list[Derived] = []
    out.extend(_fitness(inputs, day))
    out.extend(_activity(inputs, day))

    steps = inputs.get(silver.STEPS).present(day, WEEK)
    if steps:
        average = mean(steps)
        if average is not None:
            out.append(
                Derived(metric=d.STEPS_7D, calendar_date=day, value=average, inputs=len(steps))
            )
    return out


def _fitness(inputs: Inputs, day: date) -> list[Derived]:
    series = inputs.get(silver.VO2MAX_RUNNING)
    window = series.window(day, VO2MAX_SLOPE_DAYS)
    observed = sum(1 for value in window if value is not None)
    if observed == 0:
        return []

    out: list[Derived] = []
    smoothed = ewma(
        series.values[: (series.index(day) or 0) + 1], time_constant_days=VO2MAX_TAU_DAYS
    )[-1]
    if smoothed is not None:
        out.append(
            Derived(metric=d.VO2MAX_TREND, calendar_date=day, value=smoothed, inputs=observed)
        )

    if observed >= 2:
        per_day = slope(window)
        if per_day is not None:
            # Per year, because the decline this is measured against — roughly 10% a
            # decade untrained — is an annual quantity.
            out.append(
                Derived(
                    metric=d.VO2MAX_SLOPE,
                    calendar_date=day,
                    value=per_day * DAYS_PER_YEAR,
                    inputs=observed,
                )
            )
    return out


def _activity(inputs: Inputs, day: date) -> list[Derived]:
    moderate = inputs.get(silver.INTENSITY_MINUTES_MODERATE)
    vigorous = inputs.get(silver.INTENSITY_MINUTES_VIGOROUS)

    moderate_window = moderate.window(day, WEEK)
    vigorous_window = vigorous.window(day, WEEK)
    observed = sum(
        1
        for pair in zip(moderate_window, vigorous_window, strict=False)
        if pair[0] is not None or pair[1] is not None
    )
    if observed == 0:
        return []

    total = sum(value for value in moderate_window if value is not None)
    total += VIGOROUS_MULTIPLIER * sum(value for value in vigorous_window if value is not None)

    return [
        Derived(metric=d.ACTIVITY_MINUTES_WEEK, calendar_date=day, value=total, inputs=observed),
        Derived(
            metric=d.ACTIVITY_GUIDELINE_PCT,
            calendar_date=day,
            value=100.0 * total / WEEKLY_GUIDELINE_MINUTES,
            inputs=observed,
        ),
    ]
