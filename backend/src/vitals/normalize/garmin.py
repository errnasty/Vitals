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


# A night, in seconds. Below the floor it is a nap the watch mislabelled or a unit
# error; above the ceiling it is certainly a unit error. Used to *detect* the unit,
# never to coerce a number into range.
SLEEP_FLOOR_S = 30 * 60
SLEEP_CEILING_S = 20 * 3600


def _seconds(value: Any) -> int | None:
    """A sleep duration in seconds, whichever unit Garmin sent it in.

    The range endpoint and the per-day endpoint disagree about units on these fields,
    and the field names differ too, so a value that arrives as 28,800,000 is the same
    night as one that arrives as 28,800. Guessing from the field name would be
    guessing; this decides from magnitude, which for sleep is unambiguous — no real
    night is 28,800,000 seconds and none is 28.8.

    A value that is implausible in *both* readings is rejected rather than stored.
    A wrong duration is worse than a missing one: the missing one lowers coverage and
    says so, and the wrong one silently moves the sleep pillar.
    """
    number = _num(value)
    if number is None or number <= 0:
        return None
    if SLEEP_FLOOR_S <= number <= SLEEP_CEILING_S:
        return int(number)
    milliseconds = number / 1000
    if SLEEP_FLOOR_S <= milliseconds <= SLEEP_CEILING_S:
        return int(milliseconds)
    return None


def _sleep_from(payload: dict[str, Any], day: date) -> SleepRecord:
    # Two shapes, both real. The per-day endpoint nests the score under
    # `sleepScores.overall.value`; the range endpoint carries a flat `sleepScore`,
    # which is why every historical night came through scoreless.
    scores = _first(payload, "sleepScores") or {}
    overall = scores.get("overall") if isinstance(scores, dict) else None
    score = _int(overall.get("value")) if isinstance(overall, dict) else None
    if score is None:
        score = _int(_first(payload, "sleepScore", "overallSleepScore"))

    deep = _seconds(_first(payload, "deepSleepSeconds", "deepTime"))
    light = _seconds(_first(payload, "lightSleepSeconds", "lightTime"))
    rem = _seconds(_first(payload, "remSleepSeconds", "remTime"))
    awake = _seconds(_first(payload, "awakeSleepSeconds", "awakeSeconds", "awakeTime"))

    duration = _seconds(
        _first(
            payload,
            "sleepTimeSeconds",
            "totalSleepSeconds",
            "totalSleepTime",
            "sleepTime",
            "sleepTimeInSeconds",
        )
    )
    if duration is None and (deep or light or rem):
        # The stages sum to the night. Only ever used when no total was sent — a
        # derived total that disagreed with a reported one would be a second opinion
        # nobody asked for.
        duration = (deep or 0) + (light or 0) + (rem or 0)

    return SleepRecord(
        calendar_date=day,
        started_at=_utc(_first(payload, "sleepStartTimestampGMT")),
        ended_at=_utc(_first(payload, "sleepEndTimestampGMT")),
        duration_s=duration,
        deep_s=deep,
        light_s=light,
        rem_s=rem,
        awake_s=awake,
        nap_s=_seconds(_first(payload, "napTimeSeconds", "napTime")),
        score=score,
        avg_hrv=_num(_first(payload, "avgSleepHRV", "avgHrv")),
        avg_spo2=_num(_first(payload, "avgSpO2", "averageSpO2", "spO2")),
        avg_respiration=_num(_first(payload, "avgRespirationValue", "respiration")),
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


def _records(payload: Any) -> list[Any]:
    """Every record in a max-metrics response, however many it holds.

    A range request comes back as a **list**, and its length is not one. Production
    sent a list of fifteen — fifteen days of VO2max, each its own record with its own
    date on a nested block. The first version of this handled only a single-element
    list, which fixed the recent-day case and silently dropped every historical
    record in the same shape: the log went from "8 of 8 produced nothing" to "1 of 8",
    which looked like success and was one payload holding fifteen days of history.

    `split_dated` cannot do this job instead: the records carry no top-level date, so
    it has nothing to split on and stores the list whole. That is the right thing for
    bronze — the bytes arrived that way — and it makes unpacking this normalizer's
    problem.
    """
    if isinstance(payload, list):
        return payload
    return [payload]


def _flatten_buckets(container: dict[str, Any]) -> list[Any] | None:
    """A dict whose every value is a list of records, flattened — or None."""
    if not container or not all(isinstance(v, list) for v in container.values()):
        return None
    return [item for bucket in container.values() for item in bucket]


def _nested_records(payload: Any, *keys: str) -> list[Any]:
    """Per-day records out of a range response that wraps them.

    Garmin's range endpoints do not return a list of days. They return a summary
    envelope — `{startDate, endDate, periodAvgScore, hillScoreDTOList}` — with the
    days inside one of its fields, under a name that differs per endpoint and ends in
    DTO, DTOList or List about half the time.

    `split_dated` cannot unwrap these: it splits a response only when *every* item
    carries a date, and an envelope carries none at its top level. So it stores the
    envelope whole, correctly, and unwrapping is the normalizer's job.

    Reading the envelope's own top-level fields — which is what these normalizers used
    to do — finds nothing, every time, for every day. `hill_score` and
    `endurance_score` were barren on 15 of 15 payloads for exactly this reason, and
    `body_composition` on 13 of 16.
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in keys:
        found = payload.get(key)
        if isinstance(found, list) and found:
            return found
        if isinstance(found, dict):
            # A `groupMap`-style container: buckets keyed by month, each a list of
            # days. Checked before treating the dict as one record, or the whole
            # bucket map comes back as a single dateless "record".
            flattened = _flatten_buckets(found)
            if flattened is not None:
                return flattened
            # A single-day response uses the same field for one record rather than a
            # list of one.
            return [found]

    for value in payload.values():
        if isinstance(value, dict):
            flattened = _flatten_buckets(value)
            if flattened is not None:
                return flattened

    # No envelope field matched, so treat the payload as the record. This is the
    # single-day shape of the same endpoints, where the fields sit at the top level
    # rather than inside a list — and when it really is an envelope this costs
    # nothing, because none of the field names a caller looks for are on it.
    return [payload]


def _record_day(bronze: Bronze, record: Any) -> date | None:
    """The day one unwrapped record is about."""
    day = _day(_first(record, "calendarDate", "calendar_date", "date", "startDate", "weighInDate"))
    return day or bronze.calendar_date


def _vo2max(container: Any) -> tuple[Any, Any]:
    """`(running, cycling)` VO2max out of whichever nesting this response uses."""
    generic = _first(container, "generic") or {}
    cycling = _first(container, "cycling") or {}
    running_value = _first(generic, "vo2MaxPreciseValue", "vo2MaxValue")
    cycling_value = _first(cycling, "vo2MaxPreciseValue", "vo2MaxValue")
    return running_value, cycling_value


def _vo2max_day(bronze: Bronze, record: Any) -> date | None:
    """The day one record is about.

    The date lives on the nested `generic` block rather than at the top level, which
    is the other half of why this endpoint produced nothing for months. `bronze`'s own
    date is preferred when it has one, but a range response that never split has none.
    """
    for block in (_first(record, "generic"), _first(record, "cycling"), record):
        day = _day(_first(block, "calendarDate", "calendar_date", "date"))
        if day is not None:
            return day
    return bronze.calendar_date


@normalizer("max_metrics")
def max_metrics(bronze: Bronze) -> Normalized:
    """VO2max: half of the Fitness headline and the whole longevity anchor.

    Two things about the real response cost this endpoint its entire output, and
    neither was visible from the library's signature: the response is a list whose
    length is however many days it covers, and each record's date is on a nested
    block rather than at the top level. A fixture written from the shape the code
    expected passed happily while production stored nothing at all.
    """
    rows: list[DailyValue] = []
    for record in _records(bronze.payload):
        day = _vo2max_day(bronze, record)
        if day is None:
            continue
        running, cycling = _vo2max(record)
        rows.extend(_daily(day, {c.VO2MAX_RUNNING: running, c.VO2MAX_CYCLING: cycling}))
    return Normalized(daily=rows)


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
    """One row per day inside the envelope, not one row for the envelope.

    A range request returns `{startDate, endDate, periodAvgScore, hillScoreDTOList}`.
    Reading `overallScore` off that envelope finds nothing — it is on each record in
    the list — which is why this was barren on 15 of 15 payloads.
    """
    rows: list[DailyValue] = []
    for record in _nested_records(bronze.payload, "hillScoreDTOList", "hillScoreDTO"):
        day = _record_day(bronze, record)
        if day is None:
            continue
        value = _first(record, "overallScore", "hillScore", "score", "value")
        rows.extend(_daily(day, {c.HILL_SCORE: value}))
    return Normalized(daily=rows)


@normalizer("endurance_score")
def endurance_score(bronze: Bronze) -> Normalized:
    """Same envelope problem as `hill_score`, with a different field name.

    `{avg, max, startDate, endDate, groupMap, enduranceScoreDTO}`. The envelope's own
    `avg` is the *period* average across the whole range — storing that under each day
    would have been worse than storing nothing, because it would have looked right.
    """
    rows: list[DailyValue] = []
    for record in _nested_records(bronze.payload, "enduranceScoreDTO", "groupMap"):
        day = _record_day(bronze, record)
        if day is None:
            continue
        value = _first(record, "overallScore", "enduranceScore", "score", "value")
        rows.extend(_daily(day, {c.ENDURANCE_SCORE: value}))
    return Normalized(daily=rows)


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
    """Every weigh-in in the range, not the range's own average.

    `{startDate, endDate, totalAverage, dateWeightList}`. `totalAverage` is the mean
    across the whole window — a real number, and the wrong one to file under a single
    day. The weigh-ins are in `dateWeightList`, each with its own date.

    A single-day response has the fields at the top level instead, which
    `_nested_records` returns as a one-item list, so both shapes take the same path.
    """
    rows: list[DailyValue] = []
    for record in _nested_records(bronze.payload, "dateWeightList", "dailyWeightSummaries"):
        day = _record_day(bronze, record)
        if day is None:
            continue
        rows.extend(
            _daily(
                day,
                {
                    c.WEIGHT: _kg(_first(record, "weight")),
                    c.BONE_MASS: _kg(_first(record, "boneMass")),
                    c.MUSCLE_MASS: _kg(_first(record, "muscleMass")),
                    c.BODY_FAT_PCT: _first(record, "bodyFat"),
                    c.BODY_WATER_PCT: _first(record, "bodyWater"),
                    c.BMI: _first(record, "bmi"),
                },
            )
        )
    return Normalized(daily=rows)


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
