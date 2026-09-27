"""Finding the days most like this one — exactly, and without an extension.

The properties worth pinning down are the ones that make the answer mean something:
that a feature measured in thousands does not drown one measured in tens, that
yesterday does not win by being yesterday, and that a day with three readings cannot
beat a day with ten by having less to disagree about.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from vitals.analytics import similar

START = date(2026, 1, 1)


def _day(offset: int) -> date:
    return START + timedelta(days=offset)


def test_nothing_to_compare_against_is_an_empty_answer() -> None:
    assert similar.nearest({}, target=_day(0)) == []


def test_the_closest_day_is_the_one_that_actually_matches() -> None:
    rows = {
        _day(0): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        _day(10): {"hrv": 61.0, "rhr": 50.0, "sleep": 7.1, "steps": 9100.0},
        _day(20): {"hrv": 40.0, "rhr": 62.0, "sleep": 5.0, "steps": 2000.0},
        _day(30): {"hrv": 45.0, "rhr": 58.0, "sleep": 5.5, "steps": 3000.0},
    }

    found = similar.nearest(rows, target=_day(0), limit=1)

    assert [n.day for n in found] == [_day(10)]


def test_a_feature_measured_in_thousands_does_not_drown_one_measured_in_tens() -> None:
    """Euclidean distance on raw numbers is a step-count search with rounding noise.

    Day 10 matches on every physiological axis and differs on steps; day 20 matches
    on steps and differs on everything else. Unscaled, day 20 wins — and the answer
    is useless.
    """
    rows = {
        _day(0): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        # Identical body, 7,000 fewer steps.
        _day(10): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 2000.0},
        # Same steps, a completely different body.
        _day(20): {"hrv": 40.0, "rhr": 65.0, "sleep": 4.5, "steps": 9000.0},
    }

    found = similar.nearest(rows, target=_day(0), limit=1)

    # On raw Euclidean distance day 20 is 25 away and day 10 is 7,000 away, so the
    # unscaled answer is exactly backwards.
    assert [n.day for n in found] == [_day(10)]


def test_yesterday_does_not_win_by_being_yesterday() -> None:
    """The four days either side is a true answer that tells you nothing."""
    rows = {
        _day(20): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        _day(21): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        _day(19): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        _day(0): {"hrv": 59.0, "rhr": 51.0, "sleep": 7.2, "steps": 8800.0},
        _day(40): {"hrv": 30.0, "rhr": 70.0, "sleep": 4.0, "steps": 1000.0},
    }

    found = similar.nearest(rows, target=_day(20), limit=2)

    assert _day(21) not in [n.day for n in found]
    assert _day(19) not in [n.day for n in found]
    assert found[0].day == _day(0)


def test_a_day_with_too_little_in_common_is_not_offered() -> None:
    """Two numbers in common is not a comparison."""
    rows = {
        _day(0): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        _day(10): {"hrv": 60.0, "rhr": 50.0},
        _day(20): {"hrv": 58.0, "rhr": 52.0, "sleep": 6.8, "steps": 8000.0},
    }

    found = similar.nearest(rows, target=_day(0))

    assert [n.day for n in found] == [_day(20)]


def test_matching_on_fewer_axes_is_not_rewarded() -> None:
    """A day matched on three axes must not beat one matched on ten by having less
    to disagree about."""
    rows = {
        _day(0): {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0, "e": 1.0},
        # Perfect on four, missing the fifth.
        _day(10): {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0},
        # Perfect on all five.
        _day(20): {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0, "e": 1.0},
        _day(30): {"a": 5.0, "b": 5.0, "c": 5.0, "d": 5.0, "e": 5.0},
    }

    found = similar.nearest(rows, target=_day(0), limit=2)

    assert found[0].distance == pytest.approx(found[1].distance)
    assert found[0].shared >= 4
    # The fuller match reports more shared axes, which is what a screen shows.
    assert max(n.shared for n in found) == 5


def test_a_constant_feature_is_ignored_rather_than_dividing_by_nothing() -> None:
    """Dividing by a zero spread turns rounding noise into the dominant axis."""
    rows = {
        _day(0): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0, "flat": 1.0},
        _day(10): {"hrv": 61.0, "rhr": 50.0, "sleep": 7.1, "steps": 9100.0, "flat": 1.0},
        _day(20): {"hrv": 40.0, "rhr": 62.0, "sleep": 5.0, "steps": 2000.0, "flat": 1.0},
    }

    found = similar.nearest(rows, target=_day(0), limit=1)

    assert found[0].day == _day(10)
    assert "flat" not in found[0].alike
    assert "flat" not in found[0].unlike


def test_it_says_what_made_the_days_alike_and_what_did_not() -> None:
    """Otherwise it is a date with a number beside it."""
    rows = {
        _day(0): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 9000.0},
        _day(10): {"hrv": 60.0, "rhr": 50.0, "sleep": 7.0, "steps": 2000.0},
        _day(20): {"hrv": 30.0, "rhr": 70.0, "sleep": 4.0, "steps": 8000.0},
    }

    (closest, *_rest) = similar.nearest(rows, target=_day(0), limit=1)

    assert "hrv" in closest.alike
    assert closest.unlike[0] == "steps"
