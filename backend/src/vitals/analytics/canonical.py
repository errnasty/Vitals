"""The gold vocabulary: what this engine computes, and how much history each needs.

Silver holds what a device observed. Gold holds what those observations *mean* — a
training load is not measured anywhere, it is derived from every activity in the last
six weeks. So each definition carries a `window_days`, and that number does real work:
it is what "coverage" is measured against, and phase 5's score is only allowed to
trust a pillar as far as its coverage goes.

The rule from the root README applies most sharply here. Python computes every number
in this file; the LLM never does arithmetic on them, it only explains what they say.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DerivedDef:
    name: str
    unit: str
    # Days of history the value is computed over. Coverage is the fraction of them
    # that actually held an observation.
    window_days: int
    note: str = ""


def _d(name: str, unit: str, window_days: int, note: str = "") -> DerivedDef:
    return DerivedDef(name=name, unit=unit, window_days=window_days, note=note)


# ── Training load ───────────────────────────────────────────────────────────────
TRAINING_LOAD = "training_load"
CTL = "ctl"
ATL = "atl"
TSB = "tsb"
ACWR = "acwr"
MONOTONY = "monotony"
STRAIN = "strain"
# From the recording rather than the summary — see normalize/fit.py.
DECOUPLING = "decoupling"
ASCENT = "ascent"

# ── Recovery ────────────────────────────────────────────────────────────────────
HRV_BASELINE = "hrv_baseline"
HRV_DEVIATION = "hrv_deviation"
RHR_BASELINE = "rhr_baseline"
RHR_DEVIATION = "rhr_deviation"

# ── Sleep ───────────────────────────────────────────────────────────────────────
SLEEP_DEBT = "sleep_debt"
SLEEP_DURATION_7D = "sleep_duration_7d"
SLEEP_CONSISTENCY = "sleep_consistency"
SLEEP_EFFICIENCY = "sleep_efficiency"
SLEEP_DEEP_PCT = "sleep_deep_pct"
SLEEP_REM_PCT = "sleep_rem_pct"

# ── Body ────────────────────────────────────────────────────────────────────────
WEIGHT_TREND = "weight_trend"
WEIGHT_SLOPE = "weight_slope"
BODY_FAT_TREND = "body_fat_trend"

# ── Longevity ───────────────────────────────────────────────────────────────────
VO2MAX_TREND = "vo2max_trend"
VO2MAX_SLOPE = "vo2max_slope"
ACTIVITY_MINUTES_WEEK = "activity_minutes_week"
ACTIVITY_GUIDELINE_PCT = "activity_guideline_pct"
STEPS_7D = "steps_7d"

REGISTRY: dict[str, DerivedDef] = {
    d.name: d
    for d in (
        _d(TRAINING_LOAD, "au", 1, "sum of the day's activity loads; a rest day is 0"),
        _d(CTL, "au", 42, "chronic load — 'fitness'"),
        _d(ATL, "au", 7, "acute load — 'fatigue'"),
        _d(TSB, "au", 42, "ctl - atl — 'form'"),
        _d(ACWR, "ratio", 42, "atl / ctl; roughly 0.8-1.3 is the settled range"),
        _d(MONOTONY, "ratio", 7, "Foster: weekly mean load / its standard deviation"),
        _d(STRAIN, "au", 7, "Foster: weekly load x monotony"),
        _d(
            DECOUPLING,
            "%",
            1,
            "Friel: how much more the second half cost per heartbeat; needs a FIT file",
        ),
        _d(ASCENT, "m", 1, "metres climbed, from the altimeter rather than the summary"),
        _d(HRV_BASELINE, "ms", 60),
        _d(HRV_DEVIATION, "sd", 60, "today against this person's own spread"),
        _d(RHR_BASELINE, "bpm", 60),
        _d(RHR_DEVIATION, "sd", 60),
        _d(SLEEP_DEBT, "s", 14, "cumulative shortfall against the nightly need"),
        _d(SLEEP_DURATION_7D, "s", 7),
        _d(SLEEP_CONSISTENCY, "min", 14, "standard deviation of sleep midpoint"),
        _d(SLEEP_EFFICIENCY, "%", 1, "asleep / in bed"),
        _d(SLEEP_DEEP_PCT, "%", 1),
        _d(SLEEP_REM_PCT, "%", 1),
        _d(WEIGHT_TREND, "kg", 14, "smoothed; scale noise is larger than real change"),
        _d(WEIGHT_SLOPE, "kg/week", 30),
        _d(BODY_FAT_TREND, "%", 14),
        _d(VO2MAX_TREND, "ml/kg/min", 90),
        _d(VO2MAX_SLOPE, "ml/kg/min/year", 90),
        _d(ACTIVITY_MINUTES_WEEK, "min", 7, "moderate + 2x vigorous, as WHO counts them"),
        _d(ACTIVITY_GUIDELINE_PCT, "%", 7, "against 150 min/week"),
        _d(STEPS_7D, "count", 7),
    )
}


class UnknownDerived(KeyError):
    """A module emitted a name this vocabulary does not define."""


def unit_for(metric: str) -> str:
    try:
        return REGISTRY[metric].unit
    except KeyError as exc:
        raise UnknownDerived(metric) from exc


def window_for(metric: str) -> int:
    try:
        return REGISTRY[metric].window_days
    except KeyError as exc:
        raise UnknownDerived(metric) from exc
