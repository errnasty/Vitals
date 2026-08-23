"""Splitting range responses into per-day bronze rows.

Per-day rows are what make the trailing re-fetch nearly free: a week stored as one blob
would produce a whole new row whenever any single day in it changed.
"""

from __future__ import annotations

from datetime import date

import pytest

from vitals.sources.garmin.endpoints import derive_date, split_dated


def test_splits_a_list_of_dated_records() -> None:
    payload = [
        {"calendarDate": "2026-08-21", "value": 48},
        {"calendarDate": "2026-08-22", "value": 51},
    ]

    assert split_dated(payload) == [
        (date(2026, 8, 21), payload[0]),
        (date(2026, 8, 22), payload[1]),
    ]


def test_splits_a_container_holding_one_dated_list() -> None:
    """Several endpoints wrap their days in a named list: {"hrvSummaries": [...]}."""
    payload = {"userProfilePk": 123, "hrvSummaries": [{"calendarDate": "2026-08-21", "hrv": 62}]}

    assert split_dated(payload) == [(date(2026, 8, 21), {"calendarDate": "2026-08-21", "hrv": 62})]


def test_a_container_with_several_lists_is_left_whole() -> None:
    """Ambiguous is not worth guessing at: bronze keeps it verbatim either way."""
    payload = {"a": [{"calendarDate": "2026-08-21"}], "b": [{"calendarDate": "2026-08-22"}]}

    assert split_dated(payload) is None


def test_a_partially_dated_list_is_left_whole() -> None:
    """All or nothing — half a split would quietly bury the undated days in a blob."""
    payload = [{"calendarDate": "2026-08-21"}, {"value": 3}]

    assert split_dated(payload) is None


@pytest.mark.parametrize("payload", [None, [], {}, "text", 42, [1, 2, 3]])
def test_unsplittable_payloads_are_left_whole(payload: object) -> None:
    assert split_dated(payload) is None


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"calendarDate": "2026-08-21"}, date(2026, 8, 21)),
        ({"calendar_date": "2026-08-21"}, date(2026, 8, 21)),
        ({"date": "2026-08-21"}, date(2026, 8, 21)),
        # Garmin often hands back a full timestamp; only the day matters here.
        ({"calendarDate": "2026-08-21T00:00:00.0"}, date(2026, 8, 21)),
        ({"startDate": "2026-08-21"}, date(2026, 8, 21)),
        ({"calendarDate": "not-a-date"}, None),
        ({"calendarDate": 20260821}, None),
        ({"value": 3}, None),
        ("not a dict", None),
    ],
)
def test_date_derivation(item: object, expected: date | None) -> None:
    assert derive_date(item) == expected
