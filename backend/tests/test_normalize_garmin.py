"""Normalizers: Garmin's words in, canonical records out.

Pure functions, so these are payload literals in and dataclasses out — no database, no
fixtures, no network. The payload shapes are the ones `python-garminconnect` documents
for each endpoint.

The most valuable test here is `test_every_normalizer_has_a_fixture`: adding a
normalizer without a payload to prove it against is a failing test, which is the only
thing standing between "written from the library docs" and "known to produce rows".
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from vitals.normalize import canonical as c
from vitals.normalize.garmin import NORMALIZERS
from vitals.normalize.model import Bronze

DAY = date(2026, 8, 21)
# 2026-08-21T06:00:00Z, in the epoch milliseconds Garmin uses for its GMT fields.
NOON_MS = int(datetime(2026, 8, 21, 6, 0, tzinfo=UTC).timestamp() * 1000)

PAYLOADS: dict[str, object] = {
    "user_summary": {
        "calendarDate": "2026-08-21",
        "totalSteps": 12043,
        "totalDistanceMeters": 9120.5,
        "floorsAscended": 14,
        "restingHeartRate": 48,
        "minHeartRate": 42,
        "maxHeartRate": 171,
        "activeKilocalories": 812,
        "bmrKilocalories": 1690,
        "totalKilocalories": 2502,
        "moderateIntensityMinutes": 35,
        "vigorousIntensityMinutes": 22,
        "activeSeconds": 6400,
        "highlyActiveSeconds": 2100,
        "sedentarySeconds": 41000,
        "averageStressLevel": 31,
        "maxStressLevel": 89,
        "bodyBatteryHighestValue": 92,
        "bodyBatteryLowestValue": 18,
        "bodyBatteryChargedValue": 74,
        "bodyBatteryDrainedValue": 66,
    },
    "rhr_daily": {"calendarDate": "2026-08-21", "value": 48},
    "calories_daily": {
        "calendarDate": "2026-08-21",
        "active": 812,
        "resting": 1690,
        "total": 2502,
    },
    "daily_steps": {"calendarDate": "2026-08-21", "totalSteps": 12043, "totalDistance": 9120},
    "sleep_detail": {
        "dailySleepDTO": {
            "calendarDate": "2026-08-21",
            "sleepTimeSeconds": 27000,
            "napTimeSeconds": 0,
            "deepSleepSeconds": 5400,
            "lightSleepSeconds": 15000,
            "remSleepSeconds": 5400,
            "awakeSleepSeconds": 1200,
            "sleepStartTimestampGMT": NOON_MS,
            "sleepEndTimestampGMT": NOON_MS + 27000 * 1000,
            "avgSleepHRV": 68.4,
            "avgSpO2": 95.5,
            "avgRespirationValue": 13.2,
            "sleepScores": {"overall": {"value": 82, "qualifierKey": "GOOD"}},
        }
    },
    "sleep_daily": {
        "calendarDate": "2026-08-21",
        "values": {"totalSleepSeconds": 26400, "deepSleepSeconds": 5100},
    },
    "hrv_range": {
        "calendarDate": "2026-08-21",
        "lastNightAvg": 68,
        "weeklyAvg": 64,
        "lastNight5MinHigh": 97,
    },
    "body_battery": {
        "date": "2026-08-21",
        "charged": 74,
        "drained": 66,
        "bodyBatteryValuesArray": [
            [NOON_MS, 55],
            [NOON_MS + 180_000, 61],
            [NOON_MS + 360_000, 48],
        ],
    },
    "all_day_stress": {
        "calendarDate": "2026-08-21",
        "avgStressLevel": 31,
        "maxStressLevel": 89,
        "stressValuesArray": [[NOON_MS, 22], [NOON_MS + 180_000, -1], [NOON_MS + 360_000, 44]],
    },
    "training_readiness": [
        {
            "calendarDate": "2026-08-21",
            "inputContext": "SCHEDULED",
            "score": 41,
            "recoveryTime": 900,
            "sleepScore": 70,
        },
        {
            "calendarDate": "2026-08-21",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 73,
            "recoveryTime": 240,
            "sleepScore": 82,
        },
    ],
    "spo2": {
        "calendarDate": "2026-08-21",
        "averageSpO2": 95,
        "lowestSpO2": 88,
        "spO2HourlyAverages": [[NOON_MS, 96], [NOON_MS + 3_600_000, 94]],
    },
    "respiration": {
        "calendarDate": "2026-08-21",
        "avgWakingRespirationValue": 14.5,
        "lowestRespirationValue": 10.0,
        "highestRespirationValue": 21.0,
        "respirationValuesArray": [[NOON_MS, 13], [NOON_MS + 180_000, 15]],
    },
    "max_metrics": {
        "calendarDate": "2026-08-21",
        "generic": {"vo2MaxPreciseValue": 52.3, "vo2MaxValue": 52},
        "cycling": {"vo2MaxPreciseValue": 48.1},
    },
    "training_status": {
        "calendarDate": "2026-08-21",
        "mostRecentVO2Max": {"generic": {"vo2MaxPreciseValue": 51.9}},
    },
    "hill_score": {"calendarDate": "2026-08-21", "overallScore": 61},
    "endurance_score": {"calendarDate": "2026-08-21", "overallScore": 7100},
    "race_predictions": {
        "calendarDate": "2026-08-21",
        "time5K": 1205,
        "time10K": 2510,
        "timeHalfMarathon": 5610,
        "timeMarathon": 11900,
    },
    "body_composition": {
        "calendarDate": "2026-08-21",
        "weight": 72500,
        "bodyFat": 18.2,
        "bodyWater": 58.4,
        "boneMass": 3200,
        "muscleMass": 55400,
        "bmi": 22.6,
    },
    "activity": {
        "activityId": 987654321,
        "activityName": "Morning Run",
        "activityType": {"typeId": 1, "typeKey": "running"},
        "startTimeGMT": "2026-08-21 06:00:00",
        "duration": 3120.0,
        "movingDuration": 3050.0,
        "distance": 10200.0,
        "elevationGain": 88.0,
        "elevationLoss": 91.0,
        "averageSpeed": 3.27,
        "maxSpeed": 4.4,
        "calories": 740.0,
        "averageHR": 152.0,
        "maxHR": 176.0,
        "avgPower": 268.0,
        "maxPower": 410.0,
        "normPower": 274.0,
        "aerobicTrainingEffect": 3.4,
        "anaerobicTrainingEffect": 1.1,
        "activityTrainingLoad": 142.0,
    },
}


def _run(endpoint: str, *, calendar_date: date | None = DAY, entity_key: str | None = None):
    return NORMALIZERS[endpoint].fn(
        Bronze(
            endpoint=endpoint,
            payload=PAYLOADS[endpoint],
            calendar_date=calendar_date,
            entity_key=entity_key,
        )
    )


def _values(normalized) -> dict[str, float]:
    return {v.metric: v.value for v in normalized.daily}


def test_every_normalizer_has_a_fixture() -> None:
    """A normalizer with nothing to prove it against is a normalizer nobody has run."""
    assert set(NORMALIZERS) == set(PAYLOADS)


@pytest.mark.parametrize("endpoint", sorted(NORMALIZERS))
def test_every_normalizer_produces_rows(endpoint: str) -> None:
    assert _run(endpoint).row_count > 0


@pytest.mark.parametrize("endpoint", sorted(NORMALIZERS))
def test_every_emitted_metric_is_declared(endpoint: str) -> None:
    """The vocabulary is the contract; a typo here would be a column that never fills."""
    normalized = _run(endpoint)
    for value in normalized.daily:
        assert value.metric in c.REGISTRY, f"{endpoint} emitted undeclared {value.metric}"
        assert not c.is_sample(value.metric), f"{endpoint} put a sample metric in daily"
    for sample in normalized.samples:
        assert sample.metric in c.REGISTRY, f"{endpoint} emitted undeclared {sample.metric}"
        assert c.is_sample(sample.metric), f"{endpoint} put a daily metric in samples"


@pytest.mark.parametrize("endpoint", sorted(NORMALIZERS))
def test_every_normalizer_survives_junk(endpoint: str) -> None:
    """An unofficial API can return anything; none of it may raise mid-recompute."""
    for payload in (None, [], {}, "unexpected", {"unrelated": {"nested": 1}}, [1, 2, 3]):
        NORMALIZERS[endpoint].fn(
            Bronze(endpoint=endpoint, payload=payload, calendar_date=DAY, entity_key="1")
        )


@pytest.mark.parametrize("endpoint", sorted(NORMALIZERS))
def test_every_normalizer_is_pure(endpoint: str) -> None:
    """Same payload, same answer — the property the whole recompute story rests on."""
    first, second = _run(endpoint), _run(endpoint)
    assert first == second


def test_user_summary_maps_the_daily_summary() -> None:
    values = _values(_run("user_summary"))

    assert values[c.STEPS] == 12043
    assert values[c.RESTING_HR] == 48
    assert values[c.CALORIES_TOTAL] == 2502
    assert values[c.INTENSITY_MINUTES_VIGOROUS] == 22
    assert values[c.BODY_BATTERY_HIGH] == 92


def test_sleep_detail_yields_a_session_and_its_headline_metrics() -> None:
    normalized = _run("sleep_detail")
    night = normalized.sleep[0]

    assert night.calendar_date == DAY
    assert night.duration_s == 27000
    assert night.deep_s == 5400
    assert night.score == 82
    assert night.avg_hrv == 68.4
    assert night.started_at == datetime(2026, 8, 21, 6, 0, tzinfo=UTC)

    values = _values(normalized)
    assert values[c.SLEEP_DURATION] == 27000
    assert values[c.SLEEP_SCORE] == 82


def test_sleep_daily_reads_the_nested_values_block() -> None:
    values = _values(_run("sleep_daily"))
    assert values[c.SLEEP_DURATION] == 26400
    assert values[c.SLEEP_DEEP] == 5100


def test_body_composition_converts_grams_to_kilograms() -> None:
    """Garmin reports mass in grams; every consumer above silver expects kilograms."""
    values = _values(_run("body_composition"))

    assert values[c.WEIGHT] == 72.5
    assert values[c.MUSCLE_MASS] == 55.4
    assert values[c.BODY_FAT_PCT] == 18.2


def test_body_battery_derives_high_and_low_from_the_series() -> None:
    normalized = _run("body_battery")
    values = _values(normalized)

    assert len(normalized.samples) == 3
    assert values[c.BODY_BATTERY_HIGH] == 61
    assert values[c.BODY_BATTERY_LOW] == 48
    assert values[c.BODY_BATTERY_CHARGED] == 74


def test_body_battery_reads_the_column_its_descriptor_points_at() -> None:
    """Garmin has moved the level column between firmware versions; follow the descriptor."""
    payload = {
        "date": "2026-08-21",
        "bodyBatteryValueDescriptorDTOList": [
            {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
            {
                "bodyBatteryValueDescriptorIndex": 2,
                "bodyBatteryValueDescriptorKey": "bodyBatteryLevel",
            },
        ],
        "bodyBatteryValuesArray": [[NOON_MS, "MEASURED", 63]],
    }
    normalized = NORMALIZERS["body_battery"].fn(
        Bronze(endpoint="body_battery", payload=payload, calendar_date=DAY)
    )

    assert [s.value for s in normalized.samples] == [63.0]


def test_stress_samples_drop_the_not_worn_sentinel() -> None:
    """Garmin encodes "off the wrist" as -1, which must not be averaged as a low reading."""
    normalized = _run("all_day_stress")

    assert [s.value for s in normalized.samples] == [22.0, 44.0]


def test_training_readiness_prefers_the_morning_snapshot() -> None:
    values = _values(_run("training_readiness"))

    assert values[c.TRAINING_READINESS] == 73
    assert values[c.RECOVERY_TIME] == 240


def test_activity_maps_the_summary_and_keeps_the_provider_id() -> None:
    record = _run("activity", calendar_date=None, entity_key="987654321").activities[0]

    assert record.external_id == "987654321"
    assert record.activity_type == "running"
    assert record.distance_m == 10200.0
    assert record.started_at == datetime(2026, 8, 21, 6, 0, tzinfo=UTC)
    assert record.aerobic_training_effect == 3.4


def test_max_metrics_splits_running_from_cycling_vo2max() -> None:
    values = _values(_run("max_metrics"))

    assert values[c.VO2MAX_RUNNING] == 52.3
    assert values[c.VO2MAX_CYCLING] == 48.1


def test_booleans_are_never_mistaken_for_numbers() -> None:
    """`True` is an int in Python, and would otherwise become a plausible 1.0 bpm."""
    normalized = NORMALIZERS["rhr_daily"].fn(
        Bronze(endpoint="rhr_daily", payload={"value": True}, calendar_date=DAY)
    )
    assert normalized.daily == []


def test_a_payload_with_no_date_yields_nothing() -> None:
    """Better an empty result the coverage report counts than a row filed under today."""
    normalized = NORMALIZERS["rhr_daily"].fn(
        Bronze(endpoint="rhr_daily", payload={"value": 48}, calendar_date=None)
    )
    assert normalized.daily == []
