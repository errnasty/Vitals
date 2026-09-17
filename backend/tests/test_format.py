"""Formatting, which lives in Python because the UI is not allowed to do arithmetic."""

from __future__ import annotations

import pytest

from vitals.api import format as fmt


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(26400, "7h 20m"), (3000, "50m"), (0, "0m"), (None, "—"), (-3600, "-1h 0m")],
)
def test_durations_read_as_hours_and_minutes(seconds: float | None, expected: str) -> None:
    assert fmt.duration(seconds) == expected


def test_signed_values_use_a_real_minus_sign() -> None:
    """A hyphen is not a minus, and the difference shows at display sizes."""
    assert fmt.signed(-0.42, places=2, unit="kg") == "−0.42 kg"
    assert fmt.signed(0.42, places=2, unit="kg") == "+0.42 kg"


def test_large_numbers_are_grouped() -> None:
    assert fmt.number(9108.857) == "9,109"
    assert fmt.number(9108.857, places=1) == "9,108.9"


def test_negatives_use_a_real_minus_everywhere_not_just_in_signed() -> None:
    """Two formatters disagreeing about a minus sign shows up as uneven layout."""
    assert fmt.number(-39.6) == "−40"
    assert fmt.number(-1.234, places=2) == "−1.23"
    assert fmt.metric(-39.6, "au") == "−40"


def test_percentages_take_either_scale() -> None:
    assert fmt.percent(0.83) == "83%"
    assert fmt.percent(83.0, of_one=False) == "83%"


def test_nothing_ever_renders_as_none() -> None:
    """Every formatter has to have an answer for missing data, and it is a dash."""
    assert fmt.duration(None) == fmt.number(None) == fmt.percent(None) == "—"
    assert fmt.metric(None, "bpm") == "—"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (26400, "s", "7h 20m"),
        (48, "bpm", "48"),
        (1.0512, "ratio", "1.05"),
        (72.48, "kg", "72.5 kg"),
        (91.7, "%", "92%"),
        (150, "min", "150 min"),
    ],
)
def test_a_unit_decides_how_its_value_reads(value: float, unit: str, expected: str) -> None:
    assert fmt.metric(value, unit) == expected


def test_an_unknown_unit_falls_back_rather_than_guessing() -> None:
    assert fmt.metric(1.234, "furlongs") == "1.2"


@pytest.mark.parametrize(
    ("delta", "expected"), [(1.0, "up"), (-1.0, "down"), (0.0, "flat"), (None, "flat")]
)
def test_direction_matches_what_the_design_system_expects(
    delta: float | None, expected: str
) -> None:
    assert fmt.direction(delta) == expected
