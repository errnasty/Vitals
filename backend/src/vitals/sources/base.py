"""The source abstraction: pull sources and push sources, one bronze store.

Garmin is a *pull* source on a cron. Apple Health (phase 10) cannot be read
server-side, so it will be a *push* source: an iOS app POSTing JSON to an endpoint we
own. Both land in the same `raw_payload` table with a different `source` value, which
is what lets phase 3's resolver merge them per metric without either connector knowing
the other exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

# Mirrors sync_run.status.
SUCCESS = "success"
PARTIAL = "partial"
DEGRADED = "degraded"
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    status: str
    requests: int = 0
    stored: int = 0
    unchanged: int = 0
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (SUCCESS, PARTIAL)


class PullSource(Protocol):
    """A source we fetch from on a schedule."""

    name: str

    async def incremental(self, *, days: int) -> SyncOutcome: ...

    async def backfill(self, *, start: date, end: date) -> SyncOutcome: ...
