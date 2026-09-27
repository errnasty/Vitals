"""Asking a question about your own days.

The endpoint is thin because the decisions are all upstream: Python routes the
question, loads the facts, and validates that every number in the answer came from
them. What is left here is the HTTP shape, the rate guard, and being honest on screen
about which of the two answers you are reading.

`source` is never hidden. An answer composed in Python because the model was
unavailable, or because it stated a number that was not in the data, looks different
and says so — the alternative is a screen where the trustworthy answer and the
untrustworthy one are indistinguishable.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from vitals.ai import ask as ask_engine
from vitals.api.deps import CurrentUserDep, SessionDep
from vitals.db.models import AppUser

router = APIRouter(prefix="/ask", tags=["ask"])


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=ask_engine.QUESTION_MAX_CHARS)


class AnswerView(BaseModel):
    text: str
    # "model" or "python" — see the module docstring.
    source: str
    written_by_model: bool
    day: date | None
    # Which parts of the data the question reached, so a screen can say where the
    # answer came from without the reader having to trust it blindly.
    used: list[str]
    note: str | None = None


class SettingsView(BaseModel):
    share_notes_with_ai: bool
    # Said in full on the screen, because it is a promise being changed.
    explanation: str


NOTES_ON = (
    "Your day notes are included when answering a question. They are still never "
    "analysed, correlated or scored — only read."
)
NOTES_OFF = (
    "Your day notes are never sent anywhere. They are not analysed, not correlated, "
    "and not shown to a model."
)


@router.post("", response_model=AnswerView)
async def ask(body: Question, user: CurrentUserDep, session: SessionDep) -> AnswerView:
    try:
        answer = await ask_engine.answer(session, user_id=user.id, question=body.question)
    except ask_engine.TooLong as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return AnswerView(
        text=answer.text,
        source=answer.source,
        written_by_model=answer.source == ask_engine.SOURCE_MODEL,
        day=answer.day,
        used=list(answer.used),
        note=answer.note,
    )


class UpdateSettings(BaseModel):
    share_notes_with_ai: bool


@router.get("/settings", response_model=SettingsView)
async def read_settings(user: CurrentUserDep, session: SessionDep) -> SettingsView:
    row = await session.scalar(select(AppUser).where(AppUser.id == user.id))
    on = bool(row and row.share_notes_with_ai)
    return SettingsView(share_notes_with_ai=on, explanation=NOTES_ON if on else NOTES_OFF)


@router.put("/settings", response_model=SettingsView)
async def write_settings(
    body: UpdateSettings, user: CurrentUserDep, session: SessionDep
) -> SettingsView:
    row = await session.scalar(select(AppUser).where(AppUser.id == user.id))
    if row is None:  # pragma: no cover - the dependency provisioned this user
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such account")

    row.share_notes_with_ai = body.share_notes_with_ai
    await session.commit()
    return SettingsView(
        share_notes_with_ai=row.share_notes_with_ai,
        explanation=NOTES_ON if row.share_notes_with_ai else NOTES_OFF,
    )
