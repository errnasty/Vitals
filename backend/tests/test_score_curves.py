"""The scoring curves — the calibration, checkable on its own terms."""

from __future__ import annotations

import pytest

from vitals.score.curves import MIN_HISTORY, band, percentile, ramp


def test_a_ramp_maps_its_two_named_points_to_nothing_and_everything() -> None:
    assert ramp(0.0, zero_at=0.0, hundred_at=10.0) == 0.0
    assert ramp(10.0, zero_at=0.0, hundred_at=10.0) == 100.0
    assert ramp(5.0, zero_at=0.0, hundred_at=10.0) == 50.0


def test_a_ramp_runs_downhill_when_less_is_better() -> None:
    """Resting heart rate and sleep debt read this way round."""
    assert ramp(0.0, zero_at=10.0, hundred_at=0.0) == 100.0
    assert ramp(10.0, zero_at=10.0, hundred_at=0.0) == 0.0


def test_a_ramp_clamps_rather_than_rewarding_excess() -> None:
    """Twenty thousand steps is not twice as good as ten."""
    assert ramp(50.0, zero_at=0.0, hundred_at=10.0) == 100.0
    assert ramp(-50.0, zero_at=0.0, hundred_at=10.0) == 0.0


def test_a_ramp_needs_two_distinct_points() -> None:
    with pytest.raises(ValueError, match="distinct"):
        ramp(1.0, zero_at=5.0, hundred_at=5.0)


def test_a_band_gives_full_marks_across_its_range() -> None:
    for value in (0.8, 1.0, 1.3):
        assert band(value, low=0.8, high=1.3, margin=0.5) == 100.0


def test_a_band_penalises_both_too_little_and_too_much() -> None:
    """The point of a band: a collapse in training load costs as a spike does."""
    below = band(0.55, low=0.8, high=1.3, margin=0.5)
    above = band(1.55, low=0.8, high=1.3, margin=0.5)

    assert below == pytest.approx(50.0)
    assert above == pytest.approx(50.0)


def test_a_band_bottoms_out_beyond_its_margin() -> None:
    assert band(3.0, low=0.8, high=1.3, margin=0.5) == 0.0


def test_a_band_rejects_a_nonsense_range() -> None:
    with pytest.raises(ValueError, match="low must not exceed high"):
        band(1.0, low=2.0, high=1.0, margin=0.5)
    with pytest.raises(ValueError, match="margin must be positive"):
        band(1.0, low=0.8, high=1.3, margin=0.0)


def test_a_percentile_places_a_value_in_its_own_distribution() -> None:
    history = list(range(100))

    assert percentile(-1, history) == 0.0
    assert percentile(200, history) == 100.0
    assert percentile(50, history) == pytest.approx(50.5)


def test_ties_count_as_half_so_a_flat_metric_sits_in_the_middle() -> None:
    """Otherwise a barely-moving metric scores 0 or 100 on a rounding error."""
    assert percentile(5, [5] * MIN_HISTORY) == pytest.approx(50.0)


def test_a_percentile_needs_enough_history_to_mean_anything() -> None:
    assert percentile(5, [1, 2, 3]) is None
    assert percentile(5, list(range(MIN_HISTORY))) is not None
