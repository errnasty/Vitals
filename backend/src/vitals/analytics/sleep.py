"""Sleep: how much, how broken up, and how regular.

Duration is the number everyone quotes and the least interesting of the three.
Regularity — going to bed and getting up at consistent times — predicts outcomes
independently of how long you actually sleep, which is why the spread of the midpoint
is computed here as carefully as the total.
"""

from __future__ import annotations

from datetime import date, timedelta

from vitals.analytics import canonical as d
from vitals.analytics.math import circular_stdev_minutes, mean
from vitals.analytics.model import Derived
from vitals.analytics.series import Inputs
from vitals.normalize import canonical as silver

# The nightly target that sleep debt accrues against. A per-user value belongs in the
# phase-8 response profile; eight hours is the population default until then.
SLEEP_NEED_S = 8 * 3600
DEBT_DAYS = 14
CONSISTENCY_DAYS = 14
RECENT_DAYS = 7


def compute(inputs: Inputs, day: date) -> list[Derived]:
    out: list[Derived] = []
    duration = inputs.get(silver.SLEEP_DURATION)

    recent = duration.present(day, RECENT_DAYS)
    if recent:
        average = mean(recent)
        if average is not None:
            out.append(
                Derived(
                    metric=d.SLEEP_DURATION_7D,
                    calendar_date=day,
                    value=average,
                    inputs=len(recent),
                )
            )

    fortnight = duration.present(day, DEBT_DAYS)
    if fortnight:
        # Only shortfalls accumulate. A ten-hour night does not refund a short one —
        # the sleep literature is clear that the debt does not settle that cleanly.
        debt = sum(max(0.0, SLEEP_NEED_S - night) for night in fortnight)
        out.append(
            Derived(metric=d.SLEEP_DEBT, calendar_date=day, value=debt, inputs=len(fortnight))
        )

    out.extend(_consistency(inputs, day))
    out.extend(_structure(inputs, day))
    return out


def _consistency(inputs: Inputs, day: date) -> list[Derived]:
    midpoints = []
    for offset in range(CONSISTENCY_DAYS):
        night = inputs.nights.get(day - timedelta(days=offset))
        if night is not None and night.midpoint_minutes is not None:
            midpoints.append(night.midpoint_minutes)

    spread = circular_stdev_minutes(midpoints)
    if spread is None:
        return []
    return [
        Derived(
            metric=d.SLEEP_CONSISTENCY,
            calendar_date=day,
            value=spread,
            inputs=len(midpoints),
        )
    ]


def _structure(inputs: Inputs, day: date) -> list[Derived]:
    """Last night's efficiency and stage split — single-night values, not trends."""
    night = inputs.nights.get(day)
    if night is None or not night.duration_s:
        return []

    out: list[Derived] = []
    if night.started_at is not None and night.ended_at is not None:
        in_bed = (night.ended_at - night.started_at).total_seconds()
        if in_bed > 0:
            # Can exceed 100 if the provider's window excludes time awake before
            # sleep onset; clamping would hide that, so it is left as reported.
            out.append(
                Derived(
                    metric=d.SLEEP_EFFICIENCY,
                    calendar_date=day,
                    value=100.0 * night.duration_s / in_bed,
                    inputs=1,
                )
            )

    for stage_seconds, metric in ((night.deep_s, d.SLEEP_DEEP_PCT), (night.rem_s, d.SLEEP_REM_PCT)):
        if stage_seconds is not None:
            out.append(
                Derived(
                    metric=metric,
                    calendar_date=day,
                    value=100.0 * stage_seconds / night.duration_s,
                    inputs=1,
                )
            )
    return out
