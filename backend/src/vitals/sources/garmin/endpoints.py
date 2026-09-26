"""What to fetch, and how the response becomes bronze rows.

Declarative on purpose: the fetch plan is data, so `vitals sync --dry-run` can print
exactly which calls a run would make (and how many) without touching Garmin, and a
future endpoint is one row here rather than another branch in the sync loop.

The economics this encodes: **range endpoints, not per-day loops.** A year of resting
heart rate is one request through `get_rhr_daily(start, end)` and 365 through
`get_rhr_day(day)`. Backfill uses only range endpoints; the handful of genuinely
per-day endpoints run for recent days alone, where they are cheap.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

# Keys Garmin uses for "the day this record is about", in the order worth trying.
# Only ever used to *split* a range response into per-day rows; the day a per-day
# endpoint was asked for is the day we file it under, no guessing involved.
DATE_KEYS: tuple[str, ...] = (
    "calendarDate",
    "calendar_date",
    "date",
    "statisticsStartDate",
    "startDate",
    "wellnessStartDate",
)


# Chunk long backfills ourselves rather than handing Garmin a decade in one call.
# Two reasons: several endpoints reject spans beyond about a year, and the library
# chunks some of them *internally* — turning one call into a hundred requests the
# governor never sees, at whatever rate the library feels like. Our chunk is one
# governed, jittered request.
DEFAULT_SPAN_DAYS = 365
# Garmin's documented per-request limit on these two.
SLEEP_STEPS_SPAN_DAYS = 28


class Kind(Enum):
    """How the method is called."""

    RANGE = "range"  # method(start, end)
    DAY = "day"  # method(day)
    WEEKLY = "weekly"  # method(end, weeks=N)
    NO_ARGS = "no_args"  # method()


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    method: str
    kind: Kind
    # Garmin's own per-request span limit. None means "one request covers any span":
    # the library either chunks internally or the endpoint genuinely accepts a year.
    max_span_days: int | None = None
    in_backfill: bool = True
    in_incremental: bool = True
    # Per-day endpoints worth running for the last N days rather than only today,
    # because Garmin revises them retroactively.
    recent_days: int = 1
    # Extra keyword arguments the method needs on every call. `get_race_predictions`
    # is the reason this exists: it accepts either no parameters or all three, and
    # handing it a range without `_type` raises a plain ValueError.
    kwargs: tuple[tuple[str, Any], ...] = ()
    note: str = ""


# Range endpoints: the backbone of both backfill and the daily trailing window.
RANGE_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint(
        "rhr_daily",
        "get_rhr_daily",
        Kind.RANGE,
        DEFAULT_SPAN_DAYS,
        note="wellness-stats, ~1 year per request",
    ),
    Endpoint("calories_daily", "get_calories_daily", Kind.RANGE, DEFAULT_SPAN_DAYS),
    Endpoint(
        "sleep_daily",
        "get_sleep_daily",
        Kind.RANGE,
        SLEEP_STEPS_SPAN_DAYS,
        note="Garmin caps this endpoint at 28 days",
    ),
    Endpoint(
        "daily_steps",
        "get_daily_steps",
        Kind.RANGE,
        SLEEP_STEPS_SPAN_DAYS,
        note="Garmin caps this endpoint at 28 days",
    ),
    Endpoint("hrv_range", "get_hrv_data_range", Kind.RANGE, DEFAULT_SPAN_DAYS),
    Endpoint(
        "body_battery",
        "get_body_battery",
        Kind.RANGE,
        SLEEP_STEPS_SPAN_DAYS,
        note="same wellness cap as sleep and steps; a year returns HTTP 400",
    ),
    Endpoint("max_metrics", "get_max_metrics_range", Kind.RANGE, DEFAULT_SPAN_DAYS, note="VO2max"),
    Endpoint("hill_score", "get_hill_score", Kind.RANGE, DEFAULT_SPAN_DAYS),
    Endpoint("endurance_score", "get_endurance_score", Kind.RANGE, DEFAULT_SPAN_DAYS),
    Endpoint(
        "race_predictions",
        "get_race_predictions",
        Kind.RANGE,
        DEFAULT_SPAN_DAYS,
        # All three or none: a start and end without `_type` is a ValueError, not a
        # Garmin error, so it used to escape the connector and kill the whole run.
        kwargs=(("_type", "daily"),),
    ),
    Endpoint("body_composition", "get_body_composition", Kind.RANGE, DEFAULT_SPAN_DAYS),
    Endpoint(
        "weekly_intensity_minutes", "get_weekly_intensity_minutes", Kind.RANGE, DEFAULT_SPAN_DAYS
    ),
    # weeks= is capped at 52 per request, so the chunk is a year minus a day.
    Endpoint("weekly_stress", "get_weekly_stress", Kind.WEEKLY, 364),
)

# No range variant exists, so these run for recent days only. Fetching years of them
# would cost one request per endpoint per day — thousands, for data the range
# endpoints largely already cover.
DAILY_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("training_readiness", "get_training_readiness", Kind.DAY, in_backfill=False),
    Endpoint("training_status", "get_training_status", Kind.DAY, in_backfill=False),
    # Detailed stages, beyond the summary in sleep_daily. Revised retroactively.
    Endpoint("sleep_detail", "get_sleep_data", Kind.DAY, in_backfill=False, recent_days=3),
    Endpoint("all_day_stress", "get_all_day_stress", Kind.DAY, in_backfill=False, recent_days=2),
    Endpoint("spo2", "get_spo2_data", Kind.DAY, in_backfill=False, recent_days=2),
    Endpoint("respiration", "get_respiration_data", Kind.DAY, in_backfill=False, recent_days=2),
    Endpoint("user_summary", "get_user_summary", Kind.DAY, in_backfill=False, recent_days=2),
    Endpoint(
        "body_battery_events", "get_body_battery_events", Kind.DAY, in_backfill=False, recent_days=2
    ),
)

# Fetched once per activity, keyed by activity id rather than by date.
ACTIVITY_ENDPOINTS: tuple[str, ...] = ("activity", "activity_details", "activity_splits")

ALL_ENDPOINTS: tuple[Endpoint, ...] = RANGE_ENDPOINTS + DAILY_ENDPOINTS
BY_NAME: dict[str, Endpoint] = {e.name: e for e in ALL_ENDPOINTS}


def chunks(start: date, end: date, span_days: int | None) -> Iterator[tuple[date, date]]:
    """Split an inclusive window into request-sized pieces."""
    if start > end:
        return
    if span_days is None:
        yield start, end
        return
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=span_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def derive_date(item: Any) -> date | None:
    """Best-effort calendar date for one item of a range response."""
    if not isinstance(item, dict):
        return None
    for key in DATE_KEYS:
        value = item.get(key)
        if isinstance(value, str) and len(value) >= 10:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def split_dated(payload: Any) -> list[tuple[date, Any]] | None:
    """Split a range response into (day, item) pairs, or None if it does not split.

    Two shapes are handled: a plain list of dated records, and a container dict holding
    one such list (`{"hrvSummaries": [...]}`). Anything else is stored whole — bronze is
    verbatim provider JSON, so an unrecognised shape loses nothing; phase 3's
    normalizers are where a payload is finally interpreted.
    """
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        candidates = [v for v in payload.values() if isinstance(v, list) and v]
        if len(candidates) != 1:
            return None
        items = candidates[0]
    else:
        return None

    if not items:
        return None

    pairs: list[tuple[date, Any]] = []
    for item in items:
        day = derive_date(item)
        if day is None:
            # All or nothing: a half-split response would file some days correctly and
            # silently bury the rest inside a blob.
            return None
        pairs.append((day, item))
    return pairs
