"""Composing the score, and the invariant the whole waterfall rests on.

Pure functions, so every case is readings in and a decomposition out. The one that
matters most is `test_the_effects_always_sum_to_the_score`: if that ever fails, the UI
is drawing a waterfall that does not reconcile and the phase-7 model is explaining a
number with arithmetic that does not add up.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from vitals.analytics import canonical as gold
from vitals.score.compose import (
    MIN_CONTRIBUTION_COVERAGE,
    MIN_TRUSTED_COVERAGE,
    Gold,
    Reading,
    compose,
)
from vitals.score.pillars import PILLARS

DAY = date(2026, 8, 21)

# A plausible, fully-covered day.
HEALTHY = {
    gold.HRV_DEVIATION: 0.4,
    gold.RHR_DEVIATION: -0.3,
    gold.TSB: -5.0,
    gold.SLEEP_DURATION_7D: 7.2 * 3600,
    gold.SLEEP_DEBT: 4 * 3600,
    gold.SLEEP_CONSISTENCY: 32.0,
    gold.SLEEP_EFFICIENCY: 88.0,
    gold.CTL: 95.0,
    gold.ACWR: 1.05,
    gold.MONOTONY: 1.4,
    gold.VO2MAX_TREND: 52.5,
    gold.ACTIVITY_GUIDELINE_PCT: 140.0,
    gold.STEPS_7D: 9200.0,
}


def _gold(
    values: dict[str, float],
    *,
    coverage: float = 1.0,
    history: int = 400,
    day: date = DAY,
) -> Gold:
    """A Gold view holding `values` on `day`, with history behind it for percentiles."""
    readings = {}
    for metric, value in values.items():
        for offset in range(history + 1):
            readings[(metric, day - timedelta(days=offset))] = Reading(
                # A gentle drift so percentiles have a real distribution to work in.
                value=value * (1 - offset * 0.0005),
                coverage=coverage,
            )
    return Gold(readings)


def test_a_full_day_scores_and_is_trusted() -> None:
    day = compose(_gold(HEALTHY), DAY)

    assert day is not None
    assert 0 <= day.score <= 100
    assert day.coverage == pytest.approx(1.0)
    assert day.trusted is True
    assert len(day.pillars) == len(PILLARS)


def test_the_effects_always_sum_to_the_score() -> None:
    """The waterfall reconciles, for any mix of values, coverage and missing inputs."""
    rng = random.Random(20260821)

    for _ in range(200):
        values = {
            metric: value * rng.uniform(0.3, 1.8)
            for metric, value in HEALTHY.items()
            if rng.random() > 0.3  # drop a third of the inputs at random
        }
        if not values:
            continue
        readings = {}
        for metric, value in values.items():
            for offset in range(60):
                readings[(metric, DAY - timedelta(days=offset))] = Reading(
                    value=value * (1 - offset * 0.001),
                    coverage=rng.choice([0.3, 0.6, 1.0]),
                )

        day = compose(Gold(readings), DAY)
        if day is None:
            continue

        assert sum(c.effect for c in day.contributions) == pytest.approx(day.score, abs=1e-9)


def test_a_missing_input_lowers_coverage_rather_than_promoting_the_others() -> None:
    """Silently redistributing a missing input's weight would fake a complete picture."""
    without_hrv = {k: v for k, v in HEALTHY.items() if k != gold.HRV_DEVIATION}

    full = compose(_gold(HEALTHY), DAY)
    partial = compose(_gold(without_hrv), DAY)

    assert full is not None and partial is not None
    recovery = next(p for p in partial.pillars if p.name == "recovery")
    assert recovery.coverage == pytest.approx(0.6)  # 30 + 30 of 100
    assert partial.coverage < full.coverage


def test_a_thinly_covered_input_is_left_out_entirely() -> None:
    """Below the floor a reading says more about the gap than the person."""
    day = compose(_gold(HEALTHY, coverage=MIN_CONTRIBUTION_COVERAGE / 2), DAY)

    assert day is None


def test_a_personal_percentile_without_history_counts_as_uncovered() -> None:
    """Not an error and not a zero: it cannot be scored honestly yet."""
    day = compose(_gold(HEALTHY, history=5), DAY)

    assert day is not None
    training = next(p for p in day.pillars if p.name == "training")
    scored = {c.metric for c in training.contributions}

    assert gold.CTL not in scored  # needs 20 observations
    assert training.coverage < 1.0


def test_a_day_with_nothing_at_all_scores_nothing() -> None:
    assert compose(Gold({}), DAY) is None


def test_the_trust_flag_follows_the_published_floor() -> None:
    thin = compose(_gold(HEALTHY, coverage=0.3), DAY)
    thick = compose(_gold(HEALTHY, coverage=0.9), DAY)

    assert thin is not None and thick is not None
    assert thin.coverage < MIN_TRUSTED_COVERAGE and thin.trusted is False
    assert thick.coverage >= MIN_TRUSTED_COVERAGE and thick.trusted is True


def test_a_worse_day_scores_lower() -> None:
    """The direction of every curve, checked once through the whole composition."""
    rough = dict(HEALTHY)
    rough[gold.HRV_DEVIATION] = -2.5
    rough[gold.RHR_DEVIATION] = 2.5
    rough[gold.SLEEP_DEBT] = 20 * 3600
    rough[gold.SLEEP_CONSISTENCY] = 120.0
    rough[gold.ACWR] = 2.2

    good = compose(_gold(HEALTHY), DAY)
    bad = compose(_gold(rough), DAY)

    assert good is not None and bad is not None
    assert bad.score < good.score


def test_the_worst_input_is_the_biggest_negative_line_in_the_waterfall() -> None:
    """What makes 'why is it low' answerable without recomputing anything."""
    rough = dict(HEALTHY)
    rough[gold.SLEEP_DEBT] = 20 * 3600  # scores 0

    day = compose(_gold(rough), DAY)
    assert day is not None

    debt = next(c for c in day.contributions if c.metric == gold.SLEEP_DEBT)
    assert debt.points == 0.0
    assert debt.effect == 0.0


def test_pillar_scores_are_coverage_weighted_means_of_their_lines() -> None:
    day = compose(_gold(HEALTHY), DAY)
    assert day is not None

    for pillar in day.pillars:
        covered = sum(c.weight * c.coverage for c in pillar.contributions)
        expected = sum(c.points * c.weight * c.coverage for c in pillar.contributions) / covered
        assert pillar.score == pytest.approx(expected)


def test_every_contribution_carries_what_the_ui_needs_to_render_it() -> None:
    day = compose(_gold(HEALTHY), DAY)
    assert day is not None

    for contribution in day.contributions:
        assert contribution.label
        assert contribution.rationale
        assert 0 <= contribution.points <= 100
        assert contribution.weight > 0
