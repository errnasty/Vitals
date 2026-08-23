"""Turning a date window into a list of API calls, without making any.

Planning is pure and separate from execution for three reasons: `vitals sync --dry-run`
can show exactly what a run would cost before it costs it, the request count of a
multi-year backfill is assertable in a unit test, and the trailing-window arithmetic —
the part that quietly decides whether we make 30 requests a day or 300 — is testable
without a Garmin account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from vitals.sources.garmin.endpoints import (
    DAILY_ENDPOINTS,
    RANGE_ENDPOINTS,
    Endpoint,
    Kind,
    chunks,
)

# One call covering the whole window, then per-activity detail. Chunked in backfill so
# a single call cannot expand into hundreds of internal pagination requests the
# governor never sees.
ACTIVITY_WINDOW_DAYS = 90


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """One governed request, and where its response belongs in bronze."""

    endpoint: str
    method: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    # Set for per-day endpoints: the day we file the response under, taken from the
    # request rather than from the payload's local timestamps.
    calendar_date: date | None = None
    window: tuple[date, date] | None = None

    def describe(self) -> str:
        arguments = ", ".join(str(a) for a in self.args)
        if self.kwargs:
            arguments += ", " + ", ".join(f"{k}={v}" for k, v in self.kwargs.items())
        return f"{self.endpoint:<26} {self.method}({arguments})"


def _iso(day: date) -> str:
    return day.isoformat()


def _range_calls(endpoint: Endpoint, start: date, end: date) -> list[PlannedCall]:
    calls: list[PlannedCall] = []
    for chunk_start, chunk_end in chunks(start, end, endpoint.max_span_days):
        if endpoint.kind is Kind.WEEKLY:
            # get_weekly_stress(end, weeks=N): expressed backwards from the end date.
            weeks = max(1, ((chunk_end - chunk_start).days // 7) + 1)
            calls.append(
                PlannedCall(
                    endpoint.name,
                    endpoint.method,
                    (_iso(chunk_end),),
                    {"weeks": weeks},
                    window=(chunk_start, chunk_end),
                )
            )
        else:
            calls.append(
                PlannedCall(
                    endpoint.name,
                    endpoint.method,
                    (_iso(chunk_start), _iso(chunk_end)),
                    window=(chunk_start, chunk_end),
                )
            )
    return calls


def plan_incremental(*, today: date, days: int = 7) -> list[PlannedCall]:
    """The daily run: a trailing window on the range endpoints, plus recent per-day ones.

    The trailing window is the whole trick behind retroactive revisions. Garmin
    recomputes sleep scores and training status days after the fact; re-asking for the
    last week every run catches every one of those for a handful of requests, and
    bronze's content hashing means the unchanged days cost nothing but the request.
    """
    start = today - timedelta(days=max(0, days - 1))
    calls: list[PlannedCall] = []

    for endpoint in RANGE_ENDPOINTS:
        if endpoint.in_incremental:
            calls.extend(_range_calls(endpoint, start, today))

    for endpoint in DAILY_ENDPOINTS:
        if not endpoint.in_incremental:
            continue
        for offset in range(min(endpoint.recent_days, days)):
            day = today - timedelta(days=offset)
            calls.append(
                PlannedCall(
                    endpoint.name,
                    endpoint.method,
                    (_iso(day),),
                    calendar_date=day,
                    window=(day, day),
                )
            )

    calls.append(
        PlannedCall(
            "activities",
            "get_activities_by_date",
            (_iso(start), _iso(today)),
            window=(start, today),
        )
    )
    return calls


def plan_backfill(*, start: date, end: date) -> list[PlannedCall]:
    """The one-off history pull: range endpoints only, deliberately.

    Per-day endpoints have no range variant, so covering years of them would be one
    request per endpoint per day — tens of thousands, for data the range endpoints
    largely already carry. History comes from the range endpoints; the per-day detail
    accrues from here on, every day, in the incremental run.
    """
    calls: list[PlannedCall] = []
    for endpoint in RANGE_ENDPOINTS:
        if endpoint.in_backfill:
            calls.extend(_range_calls(endpoint, start, end))

    for chunk_start, chunk_end in chunks(start, end, ACTIVITY_WINDOW_DAYS):
        calls.append(
            PlannedCall(
                "activities",
                "get_activities_by_date",
                (_iso(chunk_start), _iso(chunk_end)),
                window=(chunk_start, chunk_end),
            )
        )
    return calls


def describe_plan(calls: list[PlannedCall]) -> str:
    """A human-readable plan, for `--dry-run`."""
    lines = [call.describe() for call in calls]
    per_endpoint: dict[str, int] = {}
    for call in calls:
        per_endpoint[call.endpoint] = per_endpoint.get(call.endpoint, 0) + 1

    summary = ", ".join(f"{name}×{count}" for name, count in sorted(per_endpoint.items()))
    lines.append("")
    lines.append(f"{len(calls)} request(s) before per-activity detail: {summary}")
    return "\n".join(lines)
