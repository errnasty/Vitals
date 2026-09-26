"""The statistics, argued with on their own terms.

This is the easiest thing in the app to get wrong in a way that looks convincing, so
these lean hard on the two cases that matter: a real effect must be found, and pure
noise must produce nothing. The second is the one that protects the user.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from vitals.insights import analysis

START = date(2026, 1, 1)


def days(n: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def series(values: list[float], start: date = START) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def test_a_real_effect_is_found() -> None:
    """Alcohol knocking 8ms off HRV, in a sample where it genuinely does."""
    rng = random.Random(1)
    every_third = {d for i, d in enumerate(days(120)) if i % 3 == 0}
    values = [
        (42.0 if (START + timedelta(days=i)) in every_third else 50.0) + rng.gauss(0, 3)
        for i in range(120)
    ]

    findings = analysis.analyse(
        tagged={"alcohol": every_third}, series={"hrv": series(values)}, lags=(0,)
    )

    assert len(findings) == 1
    found = findings[0]
    assert found.significant
    assert found.direction == "lower"
    assert found.delta == pytest.approx(-8.0, abs=1.5)
    assert found.p_value < 0.01


def test_pure_noise_finds_nothing() -> None:
    """The case that protects the user.

    Random tags against random numbers. An engine that reports a discovery here is
    an engine that will report discoveries forever, and every one of them will be
    wrong.
    """
    rng = random.Random(7)
    tagged = {f"tag{t}": {d for d in days(200) if rng.random() < 0.3} for t in range(6)}
    metrics = {f"metric{m}": series([rng.gauss(50, 6) for _ in range(200)]) for m in range(8)}

    findings = analysis.analyse(tagged=tagged, series=metrics)

    assert not [f for f in findings if f.significant]


def test_the_correction_is_what_suppresses_the_noise() -> None:
    """Without it the same data yields false positives — that is the whole point.

    Demonstrated by comparing against the raw p-values the very same run produced,
    so this cannot pass by the test simply being weaker than the engine.
    """
    rng = random.Random(11)
    tagged = {f"tag{t}": {d for d in days(200) if rng.random() < 0.3} for t in range(6)}
    metrics = {f"metric{m}": series([rng.gauss(50, 6) for _ in range(200)]) for m in range(8)}

    findings = analysis.analyse(tagged=tagged, series=metrics)

    uncorrected = [f for f in findings if f.p_value < 0.05]
    corrected = [f for f in findings if f.significant]
    assert uncorrected, "expected some raw p-values under .05 by chance"
    assert len(corrected) < len(uncorrected)


def test_a_thin_sample_is_refused_rather_than_reported() -> None:
    """Three tagged days cannot support a conclusion however large the gap looks."""
    tagged = {d for i, d in enumerate(days(40)) if i < 3}
    values = [20.0 if i < 3 else 60.0 for i in range(40)]

    assert analysis.analyse(tagged={"illness": tagged}, series={"hrv": series(values)}) == []


def test_an_effect_too_small_to_feel_is_not_reported() -> None:
    """Real but trivial is still not worth a sentence."""
    rng = random.Random(3)
    half = {d for i, d in enumerate(days(300)) if i % 2 == 0}
    # A tenth of a standard deviation: detectable with 300 days, meaningless to live by.
    values = [
        (50.3 if (START + timedelta(days=i)) in half else 50.0) + rng.gauss(0, 3)
        for i in range(300)
    ]

    findings = analysis.analyse(tagged={"stress": half}, series={"hrv": series(values)}, lags=(0,))

    assert findings == []


def test_lag_finds_an_effect_that_lands_the_next_day() -> None:
    """Alcohol tonight shows up in tomorrow's HRV, not tonight's."""
    rng = random.Random(5)
    drinking = {d for i, d in enumerate(days(150)) if i % 4 == 0}
    values = [
        (40.0 if (START + timedelta(days=i - 1)) in drinking else 50.0) + rng.gauss(0, 3)
        for i in range(150)
    ]

    findings = analysis.analyse(
        tagged={"alcohol": drinking}, series={"hrv": series(values)}, lags=(0, 1)
    )

    significant = [f for f in findings if f.significant]
    assert significant
    best = max(significant, key=lambda f: abs(f.effect))
    assert best.lag == 1


def test_a_metric_that_never_moves_yields_nothing() -> None:
    flat = series([50.0] * 100)
    tagged = {d for i, d in enumerate(days(100)) if i % 2 == 0}

    assert analysis.analyse(tagged={"stress": tagged}, series={"weight": flat}) == []


def test_results_do_not_change_between_runs() -> None:
    """A report that changes when you reload it is a report nobody can act on."""
    rng = random.Random(2)
    tagged = {d for i, d in enumerate(days(120)) if i % 3 == 0}
    values = [
        (44.0 if (START + timedelta(days=i)) in tagged else 50.0) + rng.gauss(0, 3)
        for i in range(120)
    ]

    first = analysis.analyse(tagged={"alcohol": tagged}, series={"hrv": series(values)})
    second = analysis.analyse(tagged={"alcohol": tagged}, series={"hrv": series(values)})

    assert [f.p_value for f in first] == [f.p_value for f in second]


def test_a_day_without_a_reading_is_dropped_not_invented() -> None:
    """Interpolating would invent the very thing being measured."""
    tagged = set(days(10))
    sparse = {START: 50.0, START + timedelta(days=5): 52.0}

    observations = analysis.observations_for(tagged_days=tagged, series=sparse, lag=0)

    assert len(observations) == 2


def test_a_p_value_of_exactly_zero_is_never_reported() -> None:
    """2000 shuffles cannot justify certainty, so the +1 keeps it honest."""
    tagged = {d for i, d in enumerate(days(100)) if i % 2 == 0}
    # A gap so large no shuffle will ever match it.
    values = [(10.0 if (START + timedelta(days=i)) in tagged else 90.0) for i in range(100)]

    findings = analysis.analyse(
        tagged={"illness": tagged}, series={"hrv": series(values)}, lags=(0,)
    )

    assert findings
    assert all(f.p_value > 0 for f in findings)
