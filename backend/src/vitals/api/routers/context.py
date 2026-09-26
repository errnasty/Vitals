"""The one endpoint where the user writes rather than reads.

Everything else in this API reports what a device measured. This records what the
person noticed, and the two are kept apart deliberately — see `db/models/context.py`
for why it is the only data here that cannot be rebuilt.

The vocabulary ships with the day, so the client never hard-codes a tag list and a
new tag appears on the screen the moment it appears in `context/canonical.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from vitals.api.deps import CurrentUserDep, SessionDep
from vitals.context import canonical, store

router = APIRouter(prefix="/context", tags=["context"])

# Nothing is remembered further back than this from the UI. Not a storage limit —
# a guard against a fat-fingered URL writing context onto a day in 1970.
MAX_BACKDATE_DAYS = 365
NOTE_MAX = 2000


class TagOption(BaseModel):
    """One entry of the vocabulary, as the screen needs to draw it."""

    name: str
    label: str
    hint: str
    icon: str
    magnitude: str | None = None


class TagValue(BaseModel):
    name: str
    magnitude: int | None = Field(default=None, ge=0, le=99)


class DayResponse(BaseModel):
    date: date
    tags: list[TagValue]
    note: str | None = None
    # Shipped with every response so a client never keeps its own copy of the list.
    vocabulary: list[TagOption]


class TagsRequest(BaseModel):
    tags: list[TagValue] = Field(default_factory=list)


class NoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=NOTE_MAX)


def _vocabulary() -> list[TagOption]:
    return [
        TagOption(
            name=tag.name,
            label=tag.label,
            hint=tag.hint,
            icon=tag.icon,
            magnitude=tag.magnitude,
        )
        for tag in canonical.TAGS
    ]


def _view(day: store.DayView) -> DayResponse:
    return DayResponse(
        date=day.calendar_date,
        tags=[TagValue(name=name, magnitude=magnitude) for name, magnitude in day.tags.items()],
        note=day.note,
        vocabulary=_vocabulary(),
    )


def _checked(on: date | None) -> date:
    today = datetime.now(UTC).date()
    when = on or today
    if when > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that day has not happened yet")
    if (today - when).days > MAX_BACKDATE_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "too far back to be remembered accurately")
    return when


@router.get("", response_model=DayResponse)
async def read_day(
    user: CurrentUserDep, session: SessionDep, day: date | None = None
) -> DayResponse:
    """A day's context, plus the vocabulary to draw it with."""
    return _view(await store.day(session, user_id=user.id, on=_checked(day)))


@router.put("/tags", response_model=DayResponse)
async def write_tags(
    body: TagsRequest, user: CurrentUserDep, session: SessionDep, day: date | None = None
) -> DayResponse:
    """Replace a day's tags with exactly this set.

    Replace rather than merge: the screen sends the whole day, and a tag just
    unticked has to disappear. A merge would make unticking impossible.
    """
    try:
        updated = await store.set_tags(
            session,
            user_id=user.id,
            on=_checked(day),
            tags=[store.Tagged(name=t.name, magnitude=t.magnitude) for t in body.tags],
        )
    except canonical.UnknownTag as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"not a known tag: {exc.args[0]}"
        ) from exc
    return _view(updated)


@router.put("/note", response_model=DayResponse)
async def write_note(
    body: NoteRequest, user: CurrentUserDep, session: SessionDep, day: date | None = None
) -> DayResponse:
    """Write or clear a day's note. Never parsed, never shown to a model."""
    return _view(await store.set_note(session, user_id=user.id, on=_checked(day), body=body.note))
