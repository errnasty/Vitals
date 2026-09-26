"""Is the data still arriving?

Written because of a specific failure. One endpoint threw a `ValueError` the
connector did not catch, the cron process died on it, and the sync service sat in
CRASHED for six days. The dashboard carried on showing numbers the whole time —
correct numbers, from the last successful run, with nothing anywhere to say they had
stopped moving. Stale data that looks live is worse than an error, because an error
gets investigated.

The rule here is one sentence: **a dashboard must never present old numbers as
current without saying so.** Everything below exists to work out when that line has
been crossed, and it is deliberately generous — a single missed cron tick is a blip,
not an incident, and an app that cries wolf at every hiccup gets ignored exactly when
it matters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import SourceConnection, SyncRun

# The cron runs every six hours, so a gap of one tick means nothing — Railway skips a
# tick when the previous run is still going, and that is the design working. Two
# missed ticks is a pattern.
STALE_AFTER_HOURS = 14
# Past this it is not a wobble, it is broken, and the wording changes to match.
BROKEN_AFTER_HOURS = 48


@dataclass(frozen=True, slots=True)
class SyncHealth:
    ok: bool
    # "fine" | "stale" | "failing" | "never" | "disconnected"
    state: str
    # A sentence for the screen, or None when there is nothing worth saying. The
    # absence of a message is the normal case and carries no UI at all.
    message: str | None
    last_success_at: datetime | None
    hours_since: int | None


def _hours(since: datetime, now: datetime) -> int:
    return max(0, int((now - since).total_seconds() // 3600))


def _plural(hours: int) -> str:
    if hours < 48:
        return f"{hours} hours"
    return f"{hours // 24} days"


async def check(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> SyncHealth:
    """Whether the numbers on screen are still being refreshed."""
    moment = now or datetime.now(UTC)

    connection = await session.scalar(
        select(SourceConnection).where(SourceConnection.user_id == user_id)
    )
    if connection is None:
        return SyncHealth(
            ok=False,
            state="disconnected",
            message=None,  # the connect prompt already covers this case
            last_success_at=None,
            hours_since=None,
        )

    last = await session.scalar(
        select(SyncRun)
        .where(SyncRun.user_id == user_id, SyncRun.status.in_(("success", "partial")))
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    succeeded = last.started_at if last is not None else connection.last_success_at

    if succeeded is None:
        return SyncHealth(
            ok=False,
            state="never",
            message="Connected, but nothing has synced yet. The first pull can take a few minutes.",
            last_success_at=None,
            hours_since=None,
        )

    hours = _hours(succeeded, moment)

    # A failing run that is still inside the stale window is not worth raising: the
    # next tick may well fix it, and the data on screen is current either way.
    if hours >= BROKEN_AFTER_HOURS:
        return SyncHealth(
            ok=False,
            state="failing",
            message=(
                f"Nothing has synced for {_plural(hours)}. What is below is the last "
                "data that arrived, not today's."
            ),
            last_success_at=succeeded,
            hours_since=hours,
        )

    if hours >= STALE_AFTER_HOURS:
        return SyncHealth(
            ok=False,
            state="stale",
            message=(
                f"The last sync was {_plural(hours)} ago. These numbers may not be today's yet."
            ),
            last_success_at=succeeded,
            hours_since=hours,
        )

    return SyncHealth(
        ok=True, state="fine", message=None, last_success_at=succeeded, hours_since=hours
    )
