"""Garmin payloads → canonical records.

One function per bronze endpoint, each pure and each tolerant. Tolerance is the design
constraint that matters: this is an unofficial API, the field names below are the ones
`python-garminconnect` documents today, and a firmware or subscription change can add,
rename or drop any of them. So every read goes through `_first`, which tries several
keys and returns None rather than raising, and a payload that yields nothing is a
normal outcome that the coverage report counts — not an exception that aborts a
recompute of seven years of history.

**Priority** settles the arguments. Several endpoints report the same metric (resting
heart rate appears in both `user_summary` and `rhr_daily`), and silver holds one value
per metric per day per source. The higher priority wins, deterministically, whatever
order the rows happened to be processed in.

Nothing here is lossy in a way that matters: bronze keeps the payload verbatim, so a
field this module ignores today is still there when a later phase wants it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from vitals.normalize import canonical as c
from vitals.normalize.model import (
    ActivityRecord,
    Bronze,
    DailyValue,
    Normalized,
    Sample,
    SleepRecord,
)

SOURCE = "garmin"

Normalizer = Callable[[Bronze], Normalized]


@dataclass(frozen=True, slots=True)
class Registration:
    endpoint: str
    fn: Normalizer
    # Higher wins when two endpoints report the same metric for the same day.
    priority: int


NORMALIZERS: dict[str, Registration] = {}


def normalizer(endpoint: str, *, priority: int = 20) -> Callable[[Normalizer], Normalizer]:
    def register(fn: Normalizer) -> Normalizer:
        NORMALIZERS[endpoint] = Registration(endpoint=endpoint, fn=fn, priority=priority)
        return fn

    return register


def priority_for(endpoint: str) -> int:
    registration = NORMALIZERS.get(endpoint)
    return registration.priority if registration else 0


# ── reading a payload without trusting it ───────────────────────────────────────


def _first(payload: Any, *keys: str) -> Any:
    """First key present with a non-null value. The alias list is the whole point."""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _num(value: Any) -> float | None:
    """A float, or None for anything that is not a plain number.

    Bools are excluded deliberately: `True` is an int in Python and would otherwise
    become a perfectly valid-looking 1.0 in the middle of a health metric.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _day(value: Any) -> date | None:
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _utc(value: Any) -> datetime | None:
    """A UTC instant from the several shapes Garmin uses for one.

    Epoch milliseconds (`sleepStartTimestampGMT`), epoch seconds, and ISO-ish strings
    with or without a `T` and with or without a zone. A naive string is read as UTC,
    because every field this is pointed at is a documented GMT field — the `*Local`
    variants are never used, since the library documents them as double-offset on some
    accounts.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if abs(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace(" ", "T")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _resolve_day(bronze: Bronze, payload: Any = None) -> date | None:
    """The day a payload is about.

    The sync files per-day endpoints under the day it *asked* for, and splits range
    responses by each item's own date, so `bronze.calendar_date` is authoritative
    whenever it is set. The payload is only consulted as a fallback.
    """
    if bronze.calendar_date is not None:
        return bronze.calendar_date
    source = payload if payload is not None else bronze.payload
    return _day(_first(source, "calendarDate", "calendar_date", "date", "statisticsStartDate"))


def _daily(day: date, values: dict[str, Any]) -> list[DailyValue]:
    """Canonical rows for every metric that actually has a number."""
    rows = []
    for metric, raw in values.items():
        number = _num(raw)
        if number is not None:
            rows.append(DailyValue(metric=metric, calendar_date=day, value=number))
    return rows


def _series(array: Any, *, value_index: int = 1) -> Iterator[tuple[datetime, float]]:
    """Walk a Garmin `[[timestamp, value], ...]` array, skipping unreadable rows.

    Garmin encodes "the watch was off my wrist" as a negative sentinel (-1, -2) in
    these arrays rather than omitting the entry. Those are not zero readings and must
    not be averaged as if they were, so they are dropped here.
    """
    if not isinstance(array, list):
        return
    for row in array:
        if not isinstance(row, list | tuple) or len(row) <= value_index:
            continue
        moment = _utc(row[0])
        value = _num(row[value_index])
        if moment is None or value is None or value < 0:
            continue
        yield moment, value


# ── daily summaries ─────────────────────────────────────────────────────────────


@normalizer("user_summary", priority=30)
def user_summary(bronze: Bronze) -> Normalized:
    """The richest daily row Garmin serves — `DailyStats` in the library's own terms."""
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None or not isinstance(payload, dict):
        return Normalized()

    return Normalized(
        daily=_daily(
            day,
            {
                c.STEPS: _first(payload, "totalSteps"),
                c.DISTANCE: _first(payload, "totalDistanceMeters"),
                c.FLOORS_ASCENDED: _first(payload, "floorsAscended"),
                c.RESTING_HR: _first(payload, "restingHeartRate"),
                c.MIN_HR: _first(payload, "minHeartRate"),
                c.MAX_HR: _first(payload, "maxHeartRate"),
                c.CALORIES_ACTIVE: _first(payload, "activeKilocalories"),
                c.CALORIES_RESTING: _first(payload, "bmrKilocalories"),
                c.CALORIES_TOTAL: _first(payload, "totalKilocalories"),
                c.INTENSITY_MINUTES_MODERATE: _first(payload, "moderateIntensityMinutes"),
                c.INTENSITY_MINUTES_VIGOROUS: _first(payload, "vigorousIntensityMinutes"),
                c.ACTIVE_SECONDS: _first(payload, "activeSeconds"),
                c.HIGHLY_ACTIVE_SECONDS: _first(payload, "highlyActiveSeconds"),
                c.SEDENTARY_SECONDS: _first(payload, "sedentarySeconds"),
                c.STRESS_AVG: _first(payload, "averageStressLevel"),
                c.STRESS_MAX: _first(payload, "maxStressLevel"),
                c.BODY_BATTERY_HIGH: _first(payload, "bodyBatteryHighestValue"),
                c.BODY_BATTERY_LOW: _first(payload, "bodyBatteryLowestValue"),
                c.BODY_BATTERY_CHARGED: _first(payload, "bodyBatteryChargedValue"),
                c.BODY_BATTERY_DRAINED: _first(payload, "bodyBatteryDrainedValue"),
            },
        )
    )


@normalizer("rhr_daily", priority=25)
def rhr_daily(bronze: Bronze) -> Normalized:
    """`[{"calendarDate": ..., "value": 52}]`, already flattened by the library."""
    day = _resolve_day(bronze)
    if day is None:
        return Normalized()
    return Normalized(daily=_daily(day, {c.RESTING_HR: _first(bronze.payload, "value")}))


@normalizer("calories_daily", priority=25)
def calories_daily(bronze: Bronze) -> Normalized:
    day = _resolve_day(bronze)
    if day is None:
        return Normalized()
    payload = bronze.payload
    return Normalized(
        daily=_daily(
            day,
            {
                c.CALORIES_ACTIVE: _first(payload, "active"),
                c.CALORIES_RESTING: _first(payload, "resting"),
                c.CALORIES_TOTAL: _first(payload, "total"),
            },
        )
    )


@normalizer("daily_steps", priority=25)
def daily_steps(bronze: Bronze) -> Normalized:
    day = _resolve_day(bronze)
    if day is None:
        return Normalized()
    payload = bronze.payload
    return Normalized(
        daily=_daily(
            day,
            {
                c.STEPS: _first(payload, "totalSteps", "steps"),
                c.DISTANCE: _first(payload, "totalDistance", "distance"),
            },
        )
    )


# ── sleep ───────────────────────────────────────────────────────────────────────


def _sleep_from(payload: dict[str, Any], day: date) -> SleepRecord:
    scores = _first(payload, "sleepScores") or {}
    overall = scores.get("overall") if isinstance(scores, dict) else None
    score = _int(overall.get("value")) if isinstance(overall, dict) else None

    return SleepRecord(
        calendar_date=day,
        started_at=_utc(_first(payload, "sleepStartTimestampGMT")),
        ended_at=_utc(_first(payload, "sleepEndTimestampGMT")),
        duration_s=_int(_first(payload, "sleepTimeSeconds", "totalSleepSeconds")),
        deep_s=_int(_first(payload, "deepSleepSeconds")),
        light_s=_int(_first(payload, "lightSleepSeconds")),
        rem_s=_int(_first(payload, "remSleepSeconds")),
        awake_s=_int(_first(payload, "awakeSleepSeconds", "awakeSeconds")),
        nap_s=_int(_first(payload, "napTimeSeconds")),
        score=score,
        avg_hrv=_num(_first(payload, "avgSleepHRV", "avgHrv")),
        avg_spo2=_num(_first(payload, "avgSpO2", "averageSpO2")),
        avg_respiration=_num(_first(payload, "avgRespirationValue")),
    )


def _sleep_metrics(record: SleepRecord) -> list[DailyValue]:
    """The headline numbers, mirrored into `metric_daily`.

    Duplication on purpose: a year-long chart of sleep duration should be one indexed
    scan of `metric_daily`, not a join against a table it does not otherwise need.
    """
    return _daily(
        record.calendar_date,
        {
            c.SLEEP_DURATION: record.duration_s,
            c.SLEEP_DEEP: record.deep_s,
            c.SLEEP_LIGHT: record.light_s,
            c.SLEEP_REM: record.rem_s,
            c.SLEEP_AWAKE: record.awake_s,
            c.NAP_DURATION: record.nap_s,
            c.SLEEP_SCORE: record.score,
        },
    )


@normalizer("sleep_detail", priority=30)
def sleep_detail(bronze: Bronze) -> Normalized:
    """`get_sleep_data` — the authoritative night, stages and all."""
    payload = bronze.payload
    if not isinstance(payload, dict):
        return Normalized()
    dto = _first(payload, "dailySleepDTO")
    if not isinstance(dto, dict):
        return Normalized()

    day = _day(_first(dto, "calendarDate")) or _resolve_day(bronze, payload)
    if day is None:
        return Normalized()

    record = _sleep_from(dto, day)
    return Normalized(sleep=[record], daily=_sleep_metrics(record))


@normalizer("sleep_daily", priority=10)
def sleep_daily(bronze: Bronze) -> Normalized:
    """The range endpoint's per-night summary — superseded by `sleep_detail` where both exist."""
    payload = bronze.payload
    if not isinstance(payload, dict):
        return Normalized()

    day = _resolve_day(bronze, payload)
    if day is None:
        return Normalized()

    # Garmin nests the numbers under `values` on this endpoint, but not always.
    values = _first(payload, "values")
    body = values if isinstance(values, dict) else payload

    record = _sleep_from(body, day)
    if record.duration_s is None and record.score is None:
        return Normalized()
    return Normalized(sleep=[record], daily=_sleep_metrics(record))


# ── recovery ────────────────────────────────────────────────────────────────────


@normalizer("hrv_range")
def hrv_range(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    # A range response splits into per-day items; a single day arrives under hrvSummary.
    summary = _first(payload, "hrvSummary") if isinstance(payload, dict) else None
    body = summary if isinstance(summary, dict) else payload

    day = _day(_first(body, "calendarDate")) or _resolve_day(bronze, body)
    if day is None:
        return Normalized()

    return Normalized(
        daily=_daily(
            day,
            {
                c.HRV_OVERNIGHT_AVG: _first(body, "lastNightAvg"),
                c.HRV_WEEKLY_AVG: _first(body, "weeklyAvg"),
                c.HRV_LAST_NIGHT_5MIN_HIGH: _first(body, "lastNight5MinHigh"),
            },
        )
    )


def _body_battery_index(payload: Any) -> int:
    """Which column of `bodyBatteryValuesArray` holds the level.

    Garmin describes its own array shape in `bodyBatteryValueDescriptorDTOList`, and
    the column order has changed between firmware versions — so read the descriptor
    when it is there rather than hardcoding a position that silently starts returning
    a different quantity.
    """
    descriptors = _first(payload, "bodyBatteryValueDescriptorDTOList")
    if isinstance(descriptors, list):
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                continue
            key = str(_first(descriptor, "bodyBatteryValueDescriptorKey", "key") or "").lower()
            index = _int(_first(descriptor, "bodyBatteryValueDescriptorIndex", "index"))
            if index is not None and "level" in key:
                return index
    return 1


@normalizer("body_battery")
def body_battery(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None or not isinstance(payload, dict):
        return Normalized()

    index = _body_battery_index(payload)
    samples = [
        Sample(metric=c.BODY_BATTERY, recorded_at=moment, value=value)
        for moment, value in _series(_first(payload, "bodyBatteryValuesArray"), value_index=index)
    ]

    values = {
        c.BODY_BATTERY_CHARGED: _first(payload, "charged", "bodyBatteryChargedValue"),
        c.BODY_BATTERY_DRAINED: _first(payload, "drained", "bodyBatteryDrainedValue"),
    }
    # High and low are not in the range response, but they are exactly max/min of the
    # series it does carry — computed here rather than left to every later consumer.
    if samples:
        levels = [s.value for s in samples]
        values[c.BODY_BATTERY_HIGH] = max(levels)
        values[c.BODY_BATTERY_LOW] = min(levels)

    return Normalized(daily=_daily(day, values), samples=samples)


@normalizer("all_day_stress")
def all_day_stress(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None or not isinstance(payload, dict):
        return Normalized()

    samples = [
        Sample(metric=c.STRESS, recorded_at=moment, value=value)
        for moment, value in _series(_first(payload, "stressValuesArray", "stressValues"))
    ]
    values = {
        c.STRESS_AVG: _first(payload, "avgStressLevel", "averageStressLevel"),
        c.STRESS_MAX: _first(payload, "maxStressLevel"),
    }
    return Normalized(daily=_daily(day, values), samples=samples)


@normalizer("training_readiness")
def training_readiness(bronze: Bronze) -> Normalized:
    """Garmin emits several snapshots a day; the morning one is the meaningful reading."""
    payload = bronze.payload
    snapshots = payload if isinstance(payload, list) else [payload]
    snapshots = [s for s in snapshots if isinstance(s, dict)]
    if not snapshots:
        return Normalized()

    chosen = next(
        (s for s in snapshots if s.get("inputContext") == "AFTER_WAKEUP_RESET"), snapshots[0]
    )
    day = _day(_first(chosen, "calendarDate")) or _resolve_day(bronze, chosen)
    if day is None:
        return Normalized()

    return Normalized(
        daily=_daily(
            day,
            {
                c.TRAINING_READINESS: _first(chosen, "score"),
                c.RECOVERY_TIME: _first(chosen, "recoveryTime"),
                c.SLEEP_SCORE: _first(chosen, "sleepScore"),
            },
        )
    )


# ── respiration ─────────────────────────────────────────────────────────────────


@normalizer("spo2")
def spo2(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None or not isinstance(payload, dict):
        return Normalized()

    samples = [
        Sample(metric=c.SPO2, recorded_at=moment, value=value)
        for moment, value in _series(
            _first(payload, "spO2HourlyAverages", "spO2ValuesArray", "wellnessSpO2ValuesArray")
        )
    ]
    values = {
        c.SPO2_AVG: _first(payload, "averageSpO2", "avgSpO2"),
        c.SPO2_LOWEST: _first(payload, "lowestSpO2"),
    }
    return Normalized(daily=_daily(day, values), samples=samples)


@normalizer("respiration")
def respiration(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None or not isinstance(payload, dict):
        return Normalized()

    samples = [
        Sample(metric=c.RESPIRATION, recorded_at=moment, value=value)
        for moment, value in _series(_first(payload, "respirationValuesArray"))
    ]
    values = {
        c.RESPIRATION_AVG: _first(payload, "avgWakingRespirationValue", "avgSleepRespirationValue"),
        c.RESPIRATION_LOWEST: _first(payload, "lowestRespirationValue"),
        c.RESPIRATION_HIGHEST: _first(payload, "highestRespirationValue"),
    }
    return Normalized(daily=_daily(day, values), samples=samples)


# ── fitness ─────────────────────────────────────────────────────────────────────


def _unwrap(payload: Any) -> Any:
    """A single-record response that arrives wrapped in a list.

    `get_max_metrics_range` returns `[{...}]` rather than `{...}`, and the record
    inside carries no top-level date, so `split_dated` cannot split it and it lands in
    bronze as the list it arrived as. Unwrapping here rather than at capture keeps
    bronze verbatim, which is the whole point of bronze.
    """
    if isinstance(payload, list) and len(payload) == 1:
        return payload[0]
    return payload


def _vo2max(container: Any) -> tuple[Any, Any]:
    """`(running, cycling)` VO2max out of whichever nesting this response uses."""
    generic = _first(container, "generic") or {}
    cycling = _first(container, "cycling") or {}
    running_value = _first(generic, "vo2MaxPreciseValue", "vo2MaxValue")
    cycling_value = _first(cycling, "vo2MaxPreciseValue", "vo2MaxValue")
    return running_value, cycling_value


@normalizer("max_metrics")
def max_metrics(bronze: Bronze) -> Normalized:
    """VO2max, which is half of the Fitness headline and the whole longevity anchor.

    Two things about the real response cost this normalizer its entire output for
    months, and neither was visible from the library's signature. The response is a
    **list of one**, not a record; and the date lives on the nested `generic` block
    rather than at the top level. A fixture written from the shape the code expected
    passed happily while production stored nothing at all, which is why the fixture
    below is now the shape Garmin actually sends.
    """
    payload = _unwrap(bronze.payload)
    running, cycling = _vo2max(payload)

    # The date is on the nested block, so it has to be looked for there before the
    # payload's own (absent) top level.
    day = bronze.calendar_date
    if day is None:
        for block in (_first(payload, "generic"), _first(payload, "cycling"), payload):
            day = _day(_first(block, "calendarDate", "calendar_date", "date"))
            if day is not None:
                break
    if day is None:
        return Normalized()

    return Normalized(daily=_daily(day, {c.VO2MAX_RUNNING: running, c.VO2MAX_CYCLING: cycling}))


@normalizer("training_status", priority=5)
def training_status(bronze: Bronze) -> Normalized:
    """Only VO2max is taken here, and only as a fallback behind `max_metrics`.

    The rest of this response is Garmin's own training-status verdict, which phase 4
    deliberately recomputes rather than trusts.
    """
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None or not isinstance(payload, dict):
        return Normalized()

    recent = _first(payload, "mostRecentVO2Max")
    if not isinstance(recent, dict):
        return Normalized()
    running, cycling = _vo2max(recent)
    return Normalized(daily=_daily(day, {c.VO2MAX_RUNNING: running, c.VO2MAX_CYCLING: cycling}))


@normalizer("hill_score")
def hill_score(bronze: Bronze) -> Normalized:
    day = _resolve_day(bronze)
    if day is None:
        return Normalized()
    value = _first(bronze.payload, "overallScore", "hillScore", "value")
    return Normalized(daily=_daily(day, {c.HILL_SCORE: value}))


@normalizer("endurance_score")
def endurance_score(bronze: Bronze) -> Normalized:
    day = _resolve_day(bronze)
    if day is None:
        return Normalized()
    value = _first(bronze.payload, "overallScore", "enduranceScore", "avg", "value")
    return Normalized(daily=_daily(day, {c.ENDURANCE_SCORE: value}))


@normalizer("race_predictions")
def race_predictions(bronze: Bronze) -> Normalized:
    day = _resolve_day(bronze)
    if day is None:
        return Normalized()
    payload = bronze.payload
    return Normalized(
        daily=_daily(
            day,
            {
                c.RACE_PREDICTION_5K: _first(payload, "time5K"),
                c.RACE_PREDICTION_10K: _first(payload, "time10K"),
                c.RACE_PREDICTION_HALF: _first(payload, "timeHalfMarathon"),
                c.RACE_PREDICTION_MARATHON: _first(payload, "timeMarathon"),
            },
        )
    )


# ── body composition ────────────────────────────────────────────────────────────

# Garmin reports these three in grams.
_GRAMS_TO_KG = 1000.0


def _kg(value: Any) -> float | None:
    grams = _num(value)
    return None if grams is None else grams / _GRAMS_TO_KG


@normalizer("body_composition")
def body_composition(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    day = _resolve_day(bronze, payload)
    if day is None:
        return Normalized()

    return Normalized(
        daily=_daily(
            day,
            {
                c.WEIGHT: _kg(_first(payload, "weight")),
                c.BONE_MASS: _kg(_first(payload, "boneMass")),
                c.MUSCLE_MASS: _kg(_first(payload, "muscleMass")),
                c.BODY_FAT_PCT: _first(payload, "bodyFat"),
                c.BODY_WATER_PCT: _first(payload, "bodyWater"),
                c.BMI: _first(payload, "bmi"),
            },
        )
    )


# ── activities ──────────────────────────────────────────────────────────────────


@normalizer("activity")
def activity(bronze: Bronze) -> Normalized:
    payload = bronze.payload
    if not isinstance(payload, dict):
        return Normalized()

    external_id = bronze.entity_key or _first(payload, "activityId")
    if external_id is None:
        return Normalized()

    type_key = None
    activity_type = _first(payload, "activityType")
    if isinstance(activity_type, dict):
        type_key = _first(activity_type, "typeKey")

    return Normalized(
        activities=[
            ActivityRecord(
                external_id=str(external_id),
                name=_first(payload, "activityName"),
                activity_type=type_key,
                started_at=_utc(_first(payload, "startTimeGMT")),
                duration_s=_num(_first(payload, "duration")),
                moving_duration_s=_num(_first(payload, "movingDuration")),
                distance_m=_num(_first(payload, "distance")),
                elevation_gain_m=_num(_first(payload, "elevationGain")),
                elevation_loss_m=_num(_first(payload, "elevationLoss")),
                avg_speed_mps=_num(_first(payload, "averageSpeed")),
                max_speed_mps=_num(_first(payload, "maxSpeed")),
                calories=_num(_first(payload, "calories")),
                avg_hr=_num(_first(payload, "averageHR")),
                max_hr=_num(_first(payload, "maxHR")),
                avg_power=_num(_first(payload, "avgPower")),
                max_power=_num(_first(payload, "maxPower")),
                normalized_power=_num(_first(payload, "normPower")),
                aerobic_training_effect=_num(_first(payload, "aerobicTrainingEffect")),
                anaerobic_training_effect=_num(_first(payload, "anaerobicTrainingEffect")),
                training_load=_num(_first(payload, "activityTrainingLoad")),
                total_sets=_int(_first(payload, "totalSets")),
                total_reps=_int(_first(payload, "totalReps")),
                total_volume_kg=_num(_first(payload, "totalVolume")),
            )
        ]
    )
