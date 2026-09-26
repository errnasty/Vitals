"""Reading and writing a day's context.

Small on purpose. The interesting decisions are in the vocabulary; this is the part
that keeps the tables honest — every tag validated before it is written, and a day
with nothing to say holding no rows rather than nine false ones.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.context.canonical import tag_for
from vitals.db.models import DayContext, DayNote


@dataclass(frozen=True, slots=True)
class Tagged:
    name: str
    magnitude: int | None = None


@dataclass
class DayView:
    calendar_date: date
    tags: dict[str, int | None] = field(default_factory=dict)
    note: str | None = None

    @property
    def empty(self) -> bool:
        return not self.tags and not self.note


async def day(session: AsyncSession, *, user_id: uuid.UUID, on: date) -> DayView:
    rows = (
        (
            await session.execute(
                select(DayContext).where(
                    DayContext.user_id == user_id, DayContext.calendar_date == on
                )
            )
        )
        .scalars()
        .all()
    )
    note = await session.scalar(
        select(DayNote).where(DayNote.user_id == user_id, DayNote.calendar_date == on)
    )
    return DayView(
        calendar_date=on,
        tags={row.tag: row.magnitude for row in rows},
        note=note.body if note is not None else None,
    )


async def span(
    session: AsyncSession, *, user_id: uuid.UUID, start: date, end: date
) -> dict[date, dict[str, int | None]]:
    """Every tagged day in a window, for the analysis in `insights`."""
    rows = (
        (
            await session.execute(
                select(DayContext).where(
                    DayContext.user_id == user_id,
                    DayContext.calendar_date >= start,
                    DayContext.calendar_date <= end,
                )
            )
        )
        .scalars()
        .all()
    )
    out: dict[date, dict[str, int | None]] = {}
    for row in rows:
        out.setdefault(row.calendar_date, {})[row.tag] = row.magnitude
    return out


async def set_tags(
    session: AsyncSession, *, user_id: uuid.UUID, on: date, tags: list[Tagged]
) -> DayView:
    """Replace a day's tags with exactly this set.

    Replace rather than merge, because the UI sends the whole day: a tag the user
    just unticked has to disappear, and a merge would make unticking impossible.
    Every name is checked against the vocabulary first, so one bad tag rejects the
    request instead of writing half of it.
    """
    for item in tags:
        tag_for(item.name)  # raises UnknownTag, before anything is written

    await session.execute(
        delete(DayContext).where(DayContext.user_id == user_id, DayContext.calendar_date == on)
    )
    if tags:
        await session.execute(
            pg_insert(DayContext).values(
                [
                    {
                        "id": uuid.uuid4(),
                        "user_id": user_id,
                        "calendar_date": on,
                        "tag": item.name,
                        "magnitude": item.magnitude,
                    }
                    for item in tags
                ]
            )
        )
    await session.commit()
    return await day(session, user_id=user_id, on=on)


async def set_note(
    session: AsyncSession, *, user_id: uuid.UUID, on: date, body: str | None
) -> DayView:
    """Write or clear a day's note. Empty text deletes the row rather than storing "" ."""
    text = (body or "").strip()
    if not text:
        await session.execute(
            delete(DayNote).where(DayNote.user_id == user_id, DayNote.calendar_date == on)
        )
    else:
        statement = pg_insert(DayNote).values(
            id=uuid.uuid4(), user_id=user_id, calendar_date=on, body=text
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_day_note_day", set_={"body": statement.excluded.body}
            )
        )
    await session.commit()
    return await day(session, user_id=user_id, on=on)
