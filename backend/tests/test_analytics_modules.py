"""The five analytics modules.

Each is a pure function of a window of silver, so every case here is a fortnight of
numbers in and an answer you can check by hand. No database, no fixtures — which is
the whole reason the modules were written to take an `Inputs` rather than a session.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from vitals.analytics import body, longevity, recovery, sleep, training
from vitals.analytics import canonical as d
from vitals.analytics.engine import SOURCE_METRICS
from vitals.analytics.series import Inputs, Night, Series, trimp
from vitals.normalize import canonical as silver

DAY = date(2026, 8, 21)
HISTORY_DAYS = 120


def _inputs(
    *,
    day: date = DAY,
    series: dict[str, dict[date, float]] | None = None,
    nights: dict[date, Night] | None = None,
    load: dict[date, float] | None = None,
) -> Inputs:
    """Build the loaded window a module sees, without going near a database."""
    start = day - timedelta(days=HISTORY_DAYS)
    span = (day - start).days + 1
    provided = series or {}

    built: dict[str, Series] = {}
    for metric in SOURCE_METRICS:
        points = provided.get(metric, {})
        values: list[float | None] = [None] * span
        for when, value in points.items():
            offset = (when - start).days
            if 0 <= offset < span:
                values[offset] = value
        built[metric] = Series(
            metric=metric, unit=silver.unit_for(metric), start=start, values=values
        )

    return Inputs(
        start=day,
        end=day,
        series=built,
        nights=nights or {},
        activity_load=load or {},
        activity_count={},
    )


def _worn(days: int, *, end: date = DAY, steps: float = 9000.0) -> dict[date, float]:
    """Evidence the watch was on the wrist — what turns a quiet day into a rest day."""
    return {end - timedelta(days=offset): steps for offset in range(days)}


def _values(rows) -> dict[str, float]:
    return {row.metric: row.value for row in rows}


# ── training ────────────────────────────────────────────────────────────────────


def test_a_worn_day_with_no_workout_is_a_rest_day_not_a_gap() -> None:
    """The distinction the whole module turns on: zero load, one observation."""
    rows = _values(training.compute(_inputs(series={silver.STEPS: _worn(60)}), DAY))

    assert rows[d.TRAINING_LOAD] == 0.0
    assert d.CTL in rows


def test_an_unworn_day_produces_no_training_load_at_all() -> None:
    """No watch means no evidence, and no evidence is not evidence of rest."""
    rows = _values(training.compute(_inputs(), DAY))

    assert d.TRAINING_LOAD not in rows
    assert d.CTL not in rows


def test_fitness_decays_through_rest_and_holds_through_absence() -> None:
    """A fortnight off decays fitness; a fortnight without the watch must not."""
    hard = {DAY - timedelta(days=offset): 200.0 for offset in range(30, 45)}

    resting = training.compute(_inputs(series={silver.STEPS: _worn(60)}, load=hard), DAY)
    absent = training.compute(
        _inputs(series={silver.STEPS: _worn(60, end=DAY - timedelta(days=30))}, load=hard), DAY
    )

    assert _values(resting)[d.CTL] < _values(absent)[d.CTL]


def test_form_is_fitness_minus_fatigue() -> None:
    load = {DAY - timedelta(days=offset): 150.0 for offset in range(40)}
    rows = _values(training.compute(_inputs(series={silver.STEPS: _worn(60)}, load=load), DAY))

    assert rows[d.TSB] == pytest.approx(rows[d.CTL] - rows[d.ATL])


def test_a_hard_week_on_top_of_an_easy_block_raises_the_acute_ratio() -> None:
    steady = {DAY - timedelta(days=offset): 50.0 for offset in range(7, 60)}
    spike = {DAY - timedelta(days=offset): 300.0 for offset in range(7)}

    rows = _values(
        training.compute(_inputs(series={silver.STEPS: _worn(60)}, load=steady | spike), DAY)
    )

    assert rows[d.ACWR] > 1.3


def test_monotony_separates_an_even_week_from_a_lumpy_one() -> None:
    """Two weeks, the same total: the one that put it all in two days is the risk."""
    even = {DAY - timedelta(days=offset): 100.0 + offset for offset in range(7)}
    lumpy = dict.fromkeys([DAY - timedelta(days=o) for o in range(7)], 10.0)
    lumpy[DAY] = 340.0
    lumpy[DAY - timedelta(days=3)] = 340.0

    even_rows = _values(training.compute(_inputs(series={silver.STEPS: _worn(60)}, load=even), DAY))
    lumpy_rows = _values(
        training.compute(_inputs(series={silver.STEPS: _worn(60)}, load=lumpy), DAY)
    )

    assert even_rows[d.MONOTONY] > lumpy_rows[d.MONOTONY]


def test_an_identical_week_is_maximally_monotonous_not_missing() -> None:
    """Zero spread makes Foster's ratio undefined, and it is the case that matters most."""
    identical = {DAY - timedelta(days=offset): 100.0 for offset in range(7)}

    rows = _values(training.compute(_inputs(series={silver.STEPS: _worn(60)}, load=identical), DAY))

    assert rows[d.MONOTONY] == training.MONOTONY_CEILING
    assert rows[d.STRAIN] == pytest.approx(700.0 * training.MONOTONY_CEILING)


def test_a_week_of_complete_rest_has_no_monotony_to_report() -> None:
    rows = _values(training.compute(_inputs(series={silver.STEPS: _worn(60)}), DAY))

    assert d.MONOTONY not in rows


def test_trimp_fills_in_where_the_device_reported_no_load() -> None:
    easy = trimp(duration_s=3600, avg_hr=120)
    hard = trimp(duration_s=3600, avg_hr=170)

    assert easy is not None and hard is not None and hard > easy
    assert trimp(duration_s=3600, avg_hr=None) is None
    # Below resting is not an easy session, it is a bad reading.
    assert trimp(duration_s=3600, avg_hr=40) is None


# ── recovery ────────────────────────────────────────────────────────────────────


def test_a_baseline_needs_enough_history_to_mean_anything() -> None:
    thin = {DAY - timedelta(days=offset): 60.0 for offset in range(1, 6)}

    rows = _values(recovery.compute(_inputs(series={silver.HRV_OVERNIGHT_AVG: thin}), DAY))

    assert d.HRV_BASELINE not in rows


def test_the_baseline_excludes_today() -> None:
    """Otherwise the excursion worth noticing damps the yardstick it is measured against."""
    history = {DAY - timedelta(days=offset): 60.0 for offset in range(1, 40)}
    today = {DAY: 20.0}

    rows = _values(
        recovery.compute(_inputs(series={silver.HRV_OVERNIGHT_AVG: history | today}), DAY)
    )

    assert rows[d.HRV_BASELINE] == pytest.approx(60.0)


def test_a_suppressed_morning_reads_as_a_negative_deviation() -> None:
    history = {DAY - timedelta(days=offset): 60.0 + (offset % 5) for offset in range(1, 40)}
    rows = _values(
        recovery.compute(_inputs(series={silver.HRV_OVERNIGHT_AVG: history | {DAY: 45.0}}), DAY)
    )

    assert rows[d.HRV_DEVIATION] < -2


def test_resting_heart_rate_gets_the_same_treatment() -> None:
    history = {DAY - timedelta(days=offset): 48.0 + (offset % 3) for offset in range(1, 40)}
    rows = _values(
        recovery.compute(_inputs(series={silver.RESTING_HR: history | {DAY: 58.0}}), DAY)
    )

    assert rows[d.RHR_BASELINE] == pytest.approx(49.0, abs=1.0)
    assert rows[d.RHR_DEVIATION] > 2


# ── sleep ───────────────────────────────────────────────────────────────────────


def test_sleep_debt_counts_shortfalls_and_ignores_surplus() -> None:
    """A ten-hour night does not refund a five-hour one."""
    nights = {DAY - timedelta(days=1): 5 * 3600.0, DAY: 10 * 3600.0}

    rows = _values(sleep.compute(_inputs(series={silver.SLEEP_DURATION: nights}), DAY))

    assert rows[d.SLEEP_DEBT] == pytest.approx(3 * 3600.0)


def test_sleep_consistency_is_the_spread_of_the_midpoint() -> None:
    """A regular sleeper who crosses midnight is regular, not wildly erratic."""
    regular = {}
    for offset in range(14):
        night = DAY - timedelta(days=offset)
        start = datetime(night.year, night.month, night.day, 23, 0, tzinfo=UTC) - timedelta(days=1)
        regular[night] = Night(
            calendar_date=night,
            started_at=start,
            ended_at=start + timedelta(hours=8),
            duration_s=8 * 3600,
            deep_s=None,
            rem_s=None,
        )

    rows = _values(sleep.compute(_inputs(nights=regular), DAY))

    assert rows[d.SLEEP_CONSISTENCY] < 5


def test_sleep_structure_is_reported_as_percentages_of_the_night() -> None:
    start = datetime(2026, 8, 20, 23, 0, tzinfo=UTC)
    night = Night(
        calendar_date=DAY,
        started_at=start,
        ended_at=start + timedelta(hours=8),
        duration_s=7 * 3600,
        deep_s=int(1.4 * 3600),
        rem_s=int(1.75 * 3600),
    )

    rows = _values(sleep.compute(_inputs(nights={DAY: night}), DAY))

    assert rows[d.SLEEP_EFFICIENCY] == pytest.approx(87.5)
    assert rows[d.SLEEP_DEEP_PCT] == pytest.approx(20.0)
    assert rows[d.SLEEP_REM_PCT] == pytest.approx(25.0)


# ── body ────────────────────────────────────────────────────────────────────────


def test_the_weight_trend_ignores_a_single_noisy_morning() -> None:
    """Day-to-day scale movement exceeds a week of real change; the trend must not chase it."""
    steady = {DAY - timedelta(days=offset): 72.0 for offset in range(1, 40)}

    rows = _values(body.compute(_inputs(series={silver.WEIGHT: steady | {DAY: 76.0}}), DAY))

    assert rows[d.WEIGHT_TREND] < 73.0


def test_the_weight_slope_is_reported_per_week() -> None:
    losing = {DAY - timedelta(days=offset): 75.0 + offset * 0.1 for offset in range(30)}

    rows = _values(body.compute(_inputs(series={silver.WEIGHT: losing}), DAY))

    assert rows[d.WEIGHT_SLOPE] == pytest.approx(-0.7, abs=0.01)


# ── longevity ───────────────────────────────────────────────────────────────────


def test_vigorous_minutes_count_double_as_the_guideline_does() -> None:
    week = {DAY - timedelta(days=offset): 0.0 for offset in range(7)}
    moderate = dict(week) | {DAY: 50.0}
    vigorous = dict(week) | {DAY: 50.0}

    rows = _values(
        longevity.compute(
            _inputs(
                series={
                    silver.INTENSITY_MINUTES_MODERATE: moderate,
                    silver.INTENSITY_MINUTES_VIGOROUS: vigorous,
                }
            ),
            DAY,
        )
    )

    assert rows[d.ACTIVITY_MINUTES_WEEK] == pytest.approx(150.0)
    assert rows[d.ACTIVITY_GUIDELINE_PCT] == pytest.approx(100.0)


def test_the_vo2max_slope_is_reported_per_year() -> None:
    """The decline it is measured against — roughly 10% a decade — is an annual quantity."""
    declining = {DAY - timedelta(days=offset): 52.0 + offset * (2.0 / 365) for offset in range(90)}

    rows = _values(longevity.compute(_inputs(series={silver.VO2MAX_RUNNING: declining}), DAY))

    assert rows[d.VO2MAX_SLOPE] == pytest.approx(-2.0, abs=0.1)


def test_steps_are_averaged_over_the_week() -> None:
    steps = {DAY - timedelta(days=offset): 10000.0 for offset in range(7)}

    rows = _values(longevity.compute(_inputs(series={silver.STEPS: steps}), DAY))

    assert rows[d.STEPS_7D] == pytest.approx(10000.0)


# ── the contract every module shares ────────────────────────────────────────────


@pytest.mark.parametrize(
    "module", [training, recovery, sleep, body, longevity], ids=lambda m: m.__name__
)
def test_every_module_survives_an_empty_window(module) -> None:
    """A new account has no history, and that is not an error condition."""
    assert module.compute(_inputs(), DAY) == []


@pytest.mark.parametrize(
    "module", [training, recovery, sleep, body, longevity], ids=lambda m: m.__name__
)
def test_every_module_emits_only_declared_metrics(module) -> None:
    """The vocabulary is the contract with phase 5's score."""
    rich = _inputs(
        series={
            silver.STEPS: _worn(90),
            silver.RESTING_HR: {DAY - timedelta(days=o): 48.0 + o % 3 for o in range(90)},
            silver.HRV_OVERNIGHT_AVG: {DAY - timedelta(days=o): 60.0 + o % 5 for o in range(90)},
            silver.SLEEP_DURATION: {DAY - timedelta(days=o): 25000.0 for o in range(90)},
            silver.WEIGHT: {DAY - timedelta(days=o): 72.0 for o in range(90)},
            silver.BODY_FAT_PCT: {DAY - timedelta(days=o): 18.0 for o in range(90)},
            silver.VO2MAX_RUNNING: {DAY - timedelta(days=o): 52.0 for o in range(90)},
            silver.INTENSITY_MINUTES_MODERATE: {DAY - timedelta(days=o): 20.0 for o in range(90)},
            silver.INTENSITY_MINUTES_VIGOROUS: {DAY - timedelta(days=o): 10.0 for o in range(90)},
        },
        load={DAY - timedelta(days=o): 90.0 for o in range(90)},
    )

    for row in module.compute(rich, DAY):
        assert row.metric in d.REGISTRY, f"{module.__name__} emitted undeclared {row.metric}"
        assert row.inputs >= 0
