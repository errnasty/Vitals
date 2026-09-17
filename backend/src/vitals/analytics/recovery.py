"""Recovery: today against your own history, never against a population.

HRV is the clearest case. A "normal" overnight HRV of 40ms and one of 120ms are both
perfectly healthy in different people, so a number means nothing until it is expressed
in that person's own spread — which is why everything here is a z-score against a
rolling personal baseline rather than a value with a threshold on it.

The baseline deliberately ends *yesterday*. Including today in the average it is
compared against would damp exactly the excursion worth noticing.
"""

from __future__ import annotations

from datetime import date, timedelta

from vitals.analytics import canonical as d
from vitals.analytics.math import mean, stdev, zscore
from vitals.analytics.model import Derived
from vitals.analytics.series import Inputs
from vitals.normalize import canonical as silver

BASELINE_DAYS = 60
# Below this, the "baseline" is noise wearing a baseline's clothes.
MIN_BASELINE_OBSERVATIONS = 14


def compute(inputs: Inputs, day: date) -> list[Derived]:
    out: list[Derived] = []
    out.extend(_baseline(inputs, day, silver.HRV_OVERNIGHT_AVG, d.HRV_BASELINE, d.HRV_DEVIATION))
    out.extend(_baseline(inputs, day, silver.RESTING_HR, d.RHR_BASELINE, d.RHR_DEVIATION))
    return out


def _baseline(
    inputs: Inputs, day: date, source: str, baseline_metric: str, deviation_metric: str
) -> list[Derived]:
    series = inputs.get(source)
    # Ending yesterday: today is the thing being judged, not part of the yardstick.
    history = series.present(day - timedelta(days=1), BASELINE_DAYS)
    if len(history) < MIN_BASELINE_OBSERVATIONS:
        return []

    average = mean(history)
    spread = stdev(history)
    if average is None:
        return []

    out = [Derived(metric=baseline_metric, calendar_date=day, value=average, inputs=len(history))]

    today = series.at(day)
    if today is not None:
        deviation = zscore(today, average, spread)
        if deviation is not None:
            out.append(
                Derived(
                    metric=deviation_metric,
                    calendar_date=day,
                    value=deviation,
                    inputs=len(history),
                )
            )
    return out
