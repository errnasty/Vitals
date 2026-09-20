"""The fetch plan: the arithmetic that decides whether a sync costs 30 requests or 3000.

None of this touches Garmin, which is the point — the request budget of a multi-year
backfill is a property worth asserting long before an account is attached.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from vitals.sources.garmin.endpoints import RANGE_ENDPOINTS, Kind, chunks
from vitals.sources.garmin.plan import plan_backfill, plan_incremental

TODAY = date(2026, 8, 23)


def _counts(calls: list) -> Counter[str]:
    return Counter(call.endpoint for call in calls)


def test_incremental_asks_for_a_trailing_window() -> None:
    """Garmin revises sleep scores and training status days later; re-ask for the week."""
    calls = plan_incremental(today=TODAY, days=7)
    rhr = next(c for c in calls if c.endpoint == "rhr_daily")

    assert rhr.args == ("2026-08-17", "2026-08-23")


def test_a_daily_run_stays_in_the_expected_budget() -> None:
    calls = plan_incremental(today=TODAY, days=7)
    assert 20 <= len(calls) <= 40, f"daily sync would make {len(calls)} requests"


def test_every_range_endpoint_is_one_request_for_a_week() -> None:
    counts = _counts(plan_incremental(today=TODAY, days=7))
    for endpoint in RANGE_ENDPOINTS:
        assert counts[endpoint.name] == 1


def test_per_day_endpoints_cover_only_recent_days() -> None:
    counts = _counts(plan_incremental(today=TODAY, days=7))

    assert counts["training_readiness"] == 1  # today only
    assert counts["sleep_detail"] == 3  # revised for a couple of days afterwards


def test_a_short_window_does_not_overfetch_per_day_endpoints() -> None:
    counts = _counts(plan_incremental(today=TODAY, days=1))
    assert counts["sleep_detail"] == 1


def test_backfill_uses_range_endpoints_not_per_day_loops() -> None:
    """The whole reason a decade of history is cheap."""
    calls = plan_backfill(start=date(2019, 1, 1), end=TODAY)
    endpoints = {call.endpoint for call in calls}

    assert "training_readiness" not in endpoints
    assert "sleep_detail" not in endpoints
    assert "rhr_daily" in endpoints


def test_seven_years_of_history_costs_hundreds_not_thousands() -> None:
    calls = plan_backfill(start=date(2019, 1, 1), end=TODAY)
    days = (TODAY - date(2019, 1, 1)).days + 1

    assert len(calls) < 500, f"{len(calls)} requests for {days} days"
    # A per-day loop over the same window would be this, per endpoint.
    assert len(calls) < days


def test_sleep_and_steps_are_chunked_at_garmins_28_day_limit() -> None:
    """Chunked by us, not inside the library, so the governor sees every request."""
    calls = plan_backfill(start=date(2026, 1, 1), end=date(2026, 3, 1))
    sleep_calls = [c for c in calls if c.endpoint == "sleep_daily"]

    assert len(sleep_calls) == 3  # 60 days / 28
    assert sleep_calls[0].args == ("2026-01-01", "2026-01-28")
    assert sleep_calls[1].args == ("2026-01-29", "2026-02-25")
    assert sleep_calls[-1].args == ("2026-02-26", "2026-03-01")


def test_weekly_endpoints_are_expressed_backwards_from_the_end_date() -> None:
    calls = plan_incremental(today=TODAY, days=7)
    weekly = next(c for c in calls if c.endpoint == "weekly_stress")

    assert weekly.args == ("2026-08-23",)
    assert weekly.kwargs == {"weeks": 1}


def test_weekly_stress_never_asks_for_more_than_a_year_at_once() -> None:
    calls = plan_backfill(start=date(2019, 1, 1), end=TODAY)
    for call in (c for c in calls if c.endpoint == "weekly_stress"):
        assert call.kwargs["weeks"] <= 52


def test_activities_are_chunked_so_pagination_stays_visible() -> None:
    """One call can paginate internally; chunking keeps each one a bounded request."""
    calls = plan_backfill(start=date(2024, 1, 1), end=date(2026, 1, 1))
    activity_calls = [c for c in calls if c.endpoint == "activities"]

    assert len(activity_calls) >= 8
    for call in activity_calls:
        start, end = call.window  # type: ignore[misc]
        assert (end - start).days <= 90


def test_per_day_calls_carry_the_day_they_were_asked_for() -> None:
    """The calendar date comes from the request, never from the payload's local fields."""
    calls = plan_incremental(today=TODAY, days=7)
    readiness = next(c for c in calls if c.endpoint == "training_readiness")

    assert readiness.calendar_date == TODAY


@pytest.mark.parametrize(
    ("span", "size", "expected"),
    [
        (30, 28, [(date(2026, 1, 1), date(2026, 1, 28)), (date(2026, 1, 29), date(2026, 1, 30))]),
        (1, 28, [(date(2026, 1, 1), date(2026, 1, 1))]),
        (5, None, [(date(2026, 1, 1), date(2026, 1, 5))]),
    ],
)
def test_chunking(span: int, size: int | None, expected: list[tuple[date, date]]) -> None:
    from datetime import timedelta

    start = date(2026, 1, 1)
    assert list(chunks(start, start + timedelta(days=span - 1), size)) == expected


def test_chunking_rejects_a_backwards_window() -> None:
    assert list(chunks(date(2026, 2, 1), date(2026, 1, 1), 28)) == []


def test_every_catalogued_endpoint_exists_on_the_library() -> None:
    """A rename upstream should fail here, not at 3am in a cron job."""
    from garminconnect import Garmin

    from vitals.sources.garmin.endpoints import ALL_ENDPOINTS

    for endpoint in ALL_ENDPOINTS:
        assert callable(getattr(Garmin, endpoint.method, None)), endpoint.method
    assert callable(Garmin.get_activities_by_date)
    for _, method in __import__(
        "vitals.sources.garmin.source", fromlist=["ACTIVITY_DETAIL"]
    ).ACTIVITY_DETAIL:
        assert callable(getattr(Garmin, method, None)), method


def test_range_endpoints_declare_a_span_limit() -> None:
    """An unchunked range endpoint is a call that can silently fan out inside the library."""
    for endpoint in RANGE_ENDPOINTS:
        if endpoint.kind in (Kind.RANGE, Kind.WEEKLY):
            assert endpoint.max_span_days is not None, endpoint.name


# ── the arguments the library actually accepts ──────────────────────────────────


def test_every_planned_call_matches_the_library_s_signature() -> None:
    """The plan is only useful if the calls in it are callable.

    Worth being precise about what this does and does not buy: it catches a method
    renamed or dropped by a library upgrade, and an argument count that cannot bind.
    It would **not** have caught the `get_race_predictions` crash — a start and an
    end bind to that signature perfectly well, and the refusal happens inside the
    method body. The test below is the one that covers that, and
    `test_garmin_source.py` covers what happens when a call raises anyway.
    """
    import inspect
    from datetime import date

    from garminconnect import Garmin

    from vitals.sources.garmin.plan import plan_backfill, plan_incremental

    calls = plan_incremental(today=date(2026, 9, 20)) + plan_backfill(
        start=date(2025, 9, 20), end=date(2026, 9, 20)
    )
    assert calls

    for call in calls:
        method = getattr(Garmin, call.method, None)
        assert method is not None, f"{call.method} is not a Garmin method"
        signature = inspect.signature(method)
        # `self` is bound at call time; everything else has to fit.
        signature.bind(None, *call.args, **call.kwargs)


def test_race_predictions_is_given_the_type_it_demands() -> None:
    """All three parameters or none — a range without `_type` is the crash above."""
    from datetime import date

    from vitals.sources.garmin.plan import plan_backfill

    predictions = [
        call
        for call in plan_backfill(start=date(2025, 9, 20), end=date(2026, 9, 20))
        if call.method == "get_race_predictions"
    ]
    assert predictions
    for call in predictions:
        assert call.kwargs.get("_type") == "daily"
        assert len(call.args) == 2
