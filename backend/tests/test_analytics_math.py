"""The numeric primitives, checked on their own terms.

Pure functions over floats, so every case here is arithmetic you can verify by hand.
That is the point of keeping them separate from the domain: an exponentially weighted
average is either right or wrong regardless of what it is averaging.
"""

from __future__ import annotations

import math

import pytest

from vitals.analytics.math import (
    circular_stdev_minutes,
    clamp,
    ewma,
    mean,
    slope,
    smoothing_factor,
    stdev,
    zscore,
)


def test_smoothing_factor_halves_over_the_time_constant() -> None:
    """τ is a real half-life, not a fudge factor: after τ days, e-fold decay."""
    alpha = smoothing_factor(42)
    assert alpha == pytest.approx(1 - math.exp(-1 / 42))
    assert 0 < alpha < 1


def test_a_zero_time_constant_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        smoothing_factor(0)


def test_ewma_starts_at_the_first_observation() -> None:
    assert ewma([10.0], time_constant_days=7)[0] == 10.0


def test_ewma_holds_its_value_across_a_gap() -> None:
    """A fortnight without a weigh-in is missing data, not weight loss."""
    out = ewma([80.0, None, None, None], time_constant_days=10)

    assert out == [80.0, 80.0, 80.0, 80.0]


def test_ewma_decays_towards_an_explicit_zero() -> None:
    """A rest day is a real zero, and fitness is supposed to decay through it."""
    out = ewma([100.0, 0.0, 0.0], time_constant_days=7)

    assert out[0] == 100.0
    assert out[2] is not None and out[2] < out[1] < out[0]  # type: ignore[operator]


def test_ewma_is_empty_before_the_first_observation() -> None:
    assert ewma([None, None], time_constant_days=7) == [None, None]


def test_mean_and_stdev_need_enough_points() -> None:
    assert mean([]) is None
    assert stdev([5.0]) is None
    assert stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.13809, rel=1e-4)


def test_zscore_refuses_a_baseline_with_no_spread() -> None:
    """Zero spread would report infinite surprise; there is no information here."""
    assert zscore(5.0, 5.0, 0.0) is None
    assert zscore(5.0, 5.0, None) is None
    assert zscore(6.0, 5.0, 2.0) == 0.5


def test_slope_uses_real_positions_not_the_order_of_the_points() -> None:
    """A month with a fortnight missing trends across the month, not across the points."""
    assert slope([1.0, None, None, 4.0]) == pytest.approx(1.0)
    assert slope([1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.0)


def test_slope_needs_two_points() -> None:
    assert slope([1.0]) is None
    assert slope([None, None]) is None


def test_circular_spread_respects_the_wrap_at_midnight() -> None:
    """23:50 and 00:10 are twenty minutes apart, not 1420."""
    across_midnight = circular_stdev_minutes([1430, 10])
    same_distance_at_noon = circular_stdev_minutes([710, 730])

    assert across_midnight is not None and across_midnight < 30
    assert same_distance_at_noon is not None
    assert across_midnight == pytest.approx(same_distance_at_noon)


def test_circular_spread_of_identical_times_is_zero() -> None:
    spread = circular_stdev_minutes([600, 600, 600])
    assert spread == 0.0
    assert not math.copysign(1, spread) < 0  # not a negative zero


def test_circular_spread_needs_two_points() -> None:
    assert circular_stdev_minutes([600]) is None


def test_clamp() -> None:
    assert clamp(5, 0, 1) == 1
    assert clamp(-5, 0, 1) == 0
    assert clamp(0.5, 0, 1) == 0.5
