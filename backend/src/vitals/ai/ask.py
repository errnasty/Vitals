"""Answering a question about someone's own days.

Same shape as the daily brief, and for the same reason: generate, check every number
against the facts the answer was written from, retry once naming the fault, then fall
back to something Python composed. A question is riskier than a brief — it invites the
model to reach for whatever it knows about sleep or heart rate in general — so the
fallback is not a degraded mode here. It is the floor, and it is always available.

What this deliberately is not is a tool-calling loop. A model that chooses its own
retrieval can choose to fetch nothing and answer from memory, which on health data is
the failure that matters. Python decides what to load, from the question's words, and
what it loaded is the only thing the answer may contain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from vitals.ai import context, grounding
from vitals.ai.openrouter import AIError, OpenRouter, Unavailable
from vitals.config import get_settings
from vitals.logging import get_logger

log = get_logger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "ask.md").read_text(encoding="utf-8")

# One retry, exactly as the brief does: a model that failed grounding twice is not
# going to succeed on the third attempt, and each one costs money.
MAX_ATTEMPTS = 2

# Longer than a brief's, shorter than an essay. A question deserves a sentence or
# three, and a cap is the cheapest guard against a model that starts explaining.
QUESTION_MAX_CHARS = 500

SOURCE_MODEL = "model"
SOURCE_PYTHON = "python"


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    source: str
    day: date | None
    # The sections the question routed to, so a screen can say where this came from.
    used: tuple[str, ...]
    # Set when the model was asked and could not be used. Never hidden.
    note: str | None = None
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class TooLong(ValueError):
    """The question is longer than anything this can usefully answer."""


async def answer(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    question: str,
    today: date | None = None,
) -> Answer:
    """One grounded answer, or the facts themselves when no model is available."""
    asked = question.strip()
    if not asked:
        raise TooLong("ask something")
    if len(asked) > QUESTION_MAX_CHARS:
        raise TooLong(
            f"that question is {len(asked)} characters; keep it under {QUESTION_MAX_CHARS}"
        )

    pack = await context.build(session, user_id=user_id, question=asked, today=today)
    note = context.stale(pack.day, today)
    if note:
        pack.sections.append(note)

    rendered = pack.render()

    try:
        client = OpenRouter.from_settings(get_settings())
    except Unavailable as exc:
        return Answer(
            text=_compose(pack),
            source=SOURCE_PYTHON,
            day=pack.day,
            used=pack.routed,
            note=str(exc),
        )

    fault: str | None = None
    attempts = 0
    prompt_tokens = completion_tokens = 0

    for _ in range(MAX_ATTEMPTS):
        attempts += 1
        user = _user_message(asked, rendered, fault)
        try:
            completion = await client.complete(system=PROMPT, user=user)
        except AIError as exc:
            log.warning("ask.model_unavailable", error=str(exc))
            return Answer(
                text=_compose(pack),
                source=SOURCE_PYTHON,
                day=pack.day,
                used=pack.routed,
                note=str(exc),
                attempts=attempts,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        prompt_tokens += completion.prompt_tokens
        completion_tokens += completion.completion_tokens

        checked = grounding.check(completion.text, rendered)
        if checked.grounded:
            return Answer(
                text=completion.text.strip(),
                source=SOURCE_MODEL,
                day=pack.day,
                used=pack.routed,
                attempts=attempts,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        fault = checked.summary
        log.warning("ask.ungrounded", attempt=attempts, fault=fault)

    return Answer(
        text=_compose(pack),
        source=SOURCE_PYTHON,
        day=pack.day,
        used=pack.routed,
        note="the model stated a number that was not in the data, twice",
        attempts=attempts,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _user_message(question: str, rendered: str, fault: str | None) -> str:
    parts = [f"QUESTION\n{question}", f"FACTS\n{rendered}"]
    if fault:
        # Named specifically, so the retry can comply rather than guess.
        parts.append(
            f"YOUR PREVIOUS ANSWER WAS REJECTED\n{fault}\n"
            "Write it again using only numbers that appear above, exactly as written."
        )
    return "\n\n".join(parts)


def _compose(pack: context.Pack) -> str:
    """The answer when there is no model, or the model could not be trusted.

    Not an apology and not an error. The facts the question routed to are the answer,
    just without prose around them — which for most questions is what was wanted.
    """
    if not pack.sections:
        return "There is no data to answer from yet."
    return pack.render()
