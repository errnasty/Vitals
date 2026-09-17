"""The canonical metric vocabulary — the whole point of the silver layer.

Bronze speaks Garmin: `WELLNESS_RESTING_HEART_RATE`, `bodyBatteryHighestValue`,
`avgSleepHRV`. Silver speaks one language, and every source is translated into it on
the way in. That is what lets phase 10 add Apple Health without a single analytics
function learning where a number came from, and what lets the resolver in this package
prefer one source over another per metric.

A metric is declared here before anything may emit it. The registry is not decoration:
`normalize.garmin` is checked against it in the test suite, so a typo'd metric name is
a failing test rather than a column of data that silently never arrives.

Units are fixed at declaration and normalizers convert *to* them — Garmin reports
weight in grams and sleep in seconds, and the analytics layer should never have to ask
which one it is holding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Cardinality = Literal["daily", "sample"]


@dataclass(frozen=True, slots=True)
class MetricDef:
    name: str
    unit: str
    cardinality: Cardinality
    note: str = ""


def _m(name: str, unit: str, cardinality: Cardinality = "daily", note: str = "") -> MetricDef:
    return MetricDef(name=name, unit=unit, cardinality=cardinality, note=note)


# ── Heart ───────────────────────────────────────────────────────────────────────
RESTING_HR = "resting_hr"
MIN_HR = "min_hr"
MAX_HR = "max_hr"

# ── Activity ────────────────────────────────────────────────────────────────────
STEPS = "steps"
DISTANCE = "distance"
FLOORS_ASCENDED = "floors_ascended"
INTENSITY_MINUTES_MODERATE = "intensity_minutes_moderate"
INTENSITY_MINUTES_VIGOROUS = "intensity_minutes_vigorous"
ACTIVE_SECONDS = "active_seconds"
HIGHLY_ACTIVE_SECONDS = "highly_active_seconds"
SEDENTARY_SECONDS = "sedentary_seconds"

# ── Energy ──────────────────────────────────────────────────────────────────────
CALORIES_ACTIVE = "calories_active"
CALORIES_RESTING = "calories_resting"
CALORIES_TOTAL = "calories_total"

# ── Sleep ───────────────────────────────────────────────────────────────────────
SLEEP_DURATION = "sleep_duration"
SLEEP_DEEP = "sleep_deep"
SLEEP_LIGHT = "sleep_light"
SLEEP_REM = "sleep_rem"
SLEEP_AWAKE = "sleep_awake"
SLEEP_SCORE = "sleep_score"
NAP_DURATION = "nap_duration"

# ── Recovery ────────────────────────────────────────────────────────────────────
HRV_OVERNIGHT_AVG = "hrv_overnight_avg"
HRV_WEEKLY_AVG = "hrv_weekly_avg"
HRV_LAST_NIGHT_5MIN_HIGH = "hrv_last_night_5min_high"
BODY_BATTERY_HIGH = "body_battery_high"
BODY_BATTERY_LOW = "body_battery_low"
BODY_BATTERY_CHARGED = "body_battery_charged"
BODY_BATTERY_DRAINED = "body_battery_drained"
STRESS_AVG = "stress_avg"
STRESS_MAX = "stress_max"
TRAINING_READINESS = "training_readiness"
RECOVERY_TIME = "recovery_time"

# ── Fitness ─────────────────────────────────────────────────────────────────────
VO2MAX_RUNNING = "vo2max_running"
VO2MAX_CYCLING = "vo2max_cycling"
HILL_SCORE = "hill_score"
ENDURANCE_SCORE = "endurance_score"
RACE_PREDICTION_5K = "race_prediction_5k"
RACE_PREDICTION_10K = "race_prediction_10k"
RACE_PREDICTION_HALF = "race_prediction_half"
RACE_PREDICTION_MARATHON = "race_prediction_marathon"

# ── Body ────────────────────────────────────────────────────────────────────────
WEIGHT = "weight"
BODY_FAT_PCT = "body_fat_pct"
BODY_WATER_PCT = "body_water_pct"
BONE_MASS = "bone_mass"
MUSCLE_MASS = "muscle_mass"
BMI = "bmi"

# ── Respiration ─────────────────────────────────────────────────────────────────
SPO2_AVG = "spo2_avg"
SPO2_LOWEST = "spo2_lowest"
RESPIRATION_AVG = "respiration_avg"
RESPIRATION_LOWEST = "respiration_lowest"
RESPIRATION_HIGHEST = "respiration_highest"

# ── Intraday samples ────────────────────────────────────────────────────────────
STRESS = "stress"
BODY_BATTERY = "body_battery"
SPO2 = "spo2"
RESPIRATION = "respiration"

REGISTRY: dict[str, MetricDef] = {
    d.name: d
    for d in (
        _m(RESTING_HR, "bpm"),
        _m(MIN_HR, "bpm"),
        _m(MAX_HR, "bpm"),
        _m(STEPS, "count"),
        _m(DISTANCE, "m"),
        _m(FLOORS_ASCENDED, "count"),
        _m(INTENSITY_MINUTES_MODERATE, "min"),
        _m(INTENSITY_MINUTES_VIGOROUS, "min"),
        _m(ACTIVE_SECONDS, "s"),
        _m(HIGHLY_ACTIVE_SECONDS, "s"),
        _m(SEDENTARY_SECONDS, "s"),
        _m(CALORIES_ACTIVE, "kcal"),
        _m(CALORIES_RESTING, "kcal", note="BMR"),
        _m(CALORIES_TOTAL, "kcal"),
        _m(SLEEP_DURATION, "s"),
        _m(SLEEP_DEEP, "s"),
        _m(SLEEP_LIGHT, "s"),
        _m(SLEEP_REM, "s"),
        _m(SLEEP_AWAKE, "s"),
        _m(SLEEP_SCORE, "score"),
        _m(NAP_DURATION, "s"),
        _m(HRV_OVERNIGHT_AVG, "ms"),
        _m(HRV_WEEKLY_AVG, "ms"),
        _m(HRV_LAST_NIGHT_5MIN_HIGH, "ms"),
        _m(BODY_BATTERY_HIGH, "level"),
        _m(BODY_BATTERY_LOW, "level"),
        _m(BODY_BATTERY_CHARGED, "level"),
        _m(BODY_BATTERY_DRAINED, "level"),
        _m(STRESS_AVG, "index"),
        _m(STRESS_MAX, "index"),
        _m(TRAINING_READINESS, "score"),
        _m(RECOVERY_TIME, "min"),
        _m(VO2MAX_RUNNING, "ml/kg/min"),
        _m(VO2MAX_CYCLING, "ml/kg/min"),
        _m(HILL_SCORE, "score"),
        _m(ENDURANCE_SCORE, "score"),
        _m(RACE_PREDICTION_5K, "s"),
        _m(RACE_PREDICTION_10K, "s"),
        _m(RACE_PREDICTION_HALF, "s"),
        _m(RACE_PREDICTION_MARATHON, "s"),
        _m(WEIGHT, "kg", note="Garmin reports grams"),
        _m(BODY_FAT_PCT, "%"),
        _m(BODY_WATER_PCT, "%"),
        _m(BONE_MASS, "kg"),
        _m(MUSCLE_MASS, "kg"),
        _m(BMI, "kg/m2"),
        _m(SPO2_AVG, "%"),
        _m(SPO2_LOWEST, "%"),
        _m(RESPIRATION_AVG, "brpm"),
        _m(RESPIRATION_LOWEST, "brpm"),
        _m(RESPIRATION_HIGHEST, "brpm"),
        _m(STRESS, "index", "sample"),
        _m(BODY_BATTERY, "level", "sample"),
        _m(SPO2, "%", "sample"),
        _m(RESPIRATION, "brpm", "sample"),
    )
}


class UnknownMetric(KeyError):
    """A normalizer emitted a name this vocabulary does not define."""


def unit_for(metric: str) -> str:
    try:
        return REGISTRY[metric].unit
    except KeyError as exc:
        raise UnknownMetric(metric) from exc


def is_sample(metric: str) -> bool:
    return REGISTRY[metric].cardinality == "sample"
