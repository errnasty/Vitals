"""The quiet daily brief: generate, verify, and fall back rather than fabricate.

The flow is short and the order of it is the whole design:

    digest → (unchanged? stop) → model → grounding check → retry once → store

Two properties are worth stating because they are what separate this from asking a
chatbot about your health data.

**The brief always exists.** No API key, no credit, provider outage, a model that
cannot stop rounding — in every one of those cases the reader gets a brief, composed
in Python from the same ranked signals the model would have been given. It is plainer.
It is never wrong. A health app that goes quiet when a vendor has a bad night has
taught its user not to rely on it.

**The brief is never stored ungrounded.** If the validator rejects both attempts, the
model's text is discarded — not stored with a warning label, not shown with a
disclaimer. A number that was not computed by Python does not reach the screen, which
is the promise at the top of the README, kept.

The retry is one attempt, not a loop. A model that invented a number once and was told
exactly which one will usually fix it; a model that does it twice is the wrong model
for the job, and paying for a third opinion is how a feature that costs nothing a day
starts costing something.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.ai import grounding, openrouter
from vitals.ai.digest import Digest
from vitals.ai.digest import load as load_digest
from vitals.config import Settings, get_settings
from vitals.db.models import SOURCE_MODEL, SOURCE_PYTHON, DailyBrief
from vitals.logging import get_logger

log = get_logger(__name__)

PROMPT = Path(__file__).parent / "prompts" / "brief.md"
# One retry, and the retry is told exactly what was wrong. See the module docstring.
MAX_ATTEMPTS = 2


@lru_cache
def system_prompt() -> str:
    return PROMPT.read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class BriefResult:
    body: str
    source: str
    grounded: bool
    attempts: int
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    # Why the model's text was not used, when it was not. Surfaced by the CLI so a
    # silent fallback is never a mystery.
    fell_back: str | None = None
    # True when a stored brief was reused because the day's facts had not changed.
    reused: bool = False

    @property
    def from_model(self) -> bool:
        return self.source == SOURCE_MODEL

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def compose(digest: Digest) -> str:
    """The Python brief: the same facts, in the same order, without the prose.

    Assembled from sentences `signals.py` already wrote, so this cannot disagree with
    what the model would have been told — it is the same text, minus the rewriting.
    """
    opening = f"{digest.score.verdict} today at {digest.score.display}."
    if digest.comparison is not None and digest.comparison.direction != "flat":
        opening = (
            f"{digest.score.verdict} today at {digest.score.display}, "
            f"{digest.comparison.delta.replace(' it', '')} your "
            f"{digest.comparison.days}-day mean of {digest.comparison.mean}."
        )

    if not digest.signals:
        return f"{opening} Nothing stands out."

    # Two at most: the fallback is a brief, not a report.
    return " ".join([opening, *(signal.sentence for signal in digest.signals[:2])])


async def generate(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    day: date | None = None,
    settings: Settings | None = None,
    client: openrouter.OpenRouter | None = None,
    force: bool = False,
) -> BriefResult | None:
    """Produce and store one day's brief. None when that day has no score."""
    settings = settings or get_settings()
    digest = await load_digest(session, user_id=user_id, day=day)
    if digest is None:
        return None

    existing = await session.scalar(
        select(DailyBrief).where(
            DailyBrief.user_id == user_id, DailyBrief.calendar_date == digest.calendar_date
        )
    )
    if (
        existing is not None
        and existing.digest_fingerprint == digest.fingerprint
        and not (force or settings.ai_force_regenerate)
    ):
        # The day's facts have not moved. Rewriting them would cost money to produce
        # a differently-worded version of the same sentence.
        return BriefResult(
            body=existing.body,
            source=existing.source,
            grounded=existing.grounded,
            attempts=existing.attempts,
            model=existing.model,
            prompt_tokens=existing.prompt_tokens,
            completion_tokens=existing.completion_tokens,
            cost_usd=existing.cost_usd,
            reused=True,
        )

    result = await _write(digest, settings=settings, client=client)
    await _store(session, user_id=user_id, digest=digest, result=result)
    return result


async def _write(
    digest: Digest, *, settings: Settings, client: openrouter.OpenRouter | None
) -> BriefResult:
    """The model's attempt, or Python's, with the reason recorded either way."""
    rendered = digest.render()

    if client is None:
        try:
            client = openrouter.OpenRouter.from_settings(settings)
        except openrouter.Unavailable as exc:
            return BriefResult(
                body=compose(digest),
                source=SOURCE_PYTHON,
                grounded=True,
                attempts=0,
                fell_back=str(exc),
            )

    user = rendered
    tokens_in = tokens_out = 0
    cost: float | None = None
    last_reason = "the model could not stay grounded"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            completion = await client.complete(system=system_prompt(), user=user)
        except openrouter.AIError as exc:
            log.warning("brief.model_failed", attempt=attempt, error=str(exc))
            return BriefResult(
                body=compose(digest),
                source=SOURCE_PYTHON,
                grounded=True,
                attempts=attempt,
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                cost_usd=cost,
                fell_back=f"{type(exc).__name__}: {exc}",
            )

        tokens_in += completion.prompt_tokens
        tokens_out += completion.completion_tokens
        if completion.cost_usd is not None:
            cost = (cost or 0.0) + completion.cost_usd

        checked = grounding.check(completion.text, rendered)
        if checked.grounded:
            return BriefResult(
                body=completion.text,
                source=SOURCE_MODEL,
                grounded=True,
                attempts=attempt,
                model=completion.model,
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                cost_usd=cost,
            )

        last_reason = checked.summary
        log.info("brief.ungrounded", attempt=attempt, violations=checked.summary)
        # Name the fault rather than repeating the instruction: a model that broke a
        # rule it was already given needs to know which number it invented.
        user = (
            f"{rendered}\n\n"
            "YOUR PREVIOUS ATTEMPT WAS REJECTED.\n"
            f"{completion.text}\n\n"
            f"Why: {checked.summary}\n"
            "Rewrite it. Use only numbers that appear above, exactly as written there, "
            "or write the sentence with no number in it."
        )

    return BriefResult(
        body=compose(digest),
        source=SOURCE_PYTHON,
        grounded=True,
        attempts=MAX_ATTEMPTS,
        prompt_tokens=tokens_in,
        completion_tokens=tokens_out,
        cost_usd=cost,
        fell_back=last_reason,
    )


async def _store(
    session: AsyncSession, *, user_id: uuid.UUID, digest: Digest, result: BriefResult
) -> None:
    statement = pg_insert(DailyBrief).values(
        id=uuid.uuid4(),
        user_id=user_id,
        calendar_date=digest.calendar_date,
        body=result.body,
        source=result.source,
        model=result.model,
        digest_fingerprint=digest.fingerprint,
        grounded=result.grounded,
        attempts=result.attempts,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_daily_brief_day",
            set_={
                "body": statement.excluded.body,
                "source": statement.excluded.source,
                "model": statement.excluded.model,
                "digest_fingerprint": statement.excluded.digest_fingerprint,
                "grounded": statement.excluded.grounded,
                "attempts": statement.excluded.attempts,
                "prompt_tokens": statement.excluded.prompt_tokens,
                "completion_tokens": statement.excluded.completion_tokens,
                "cost_usd": statement.excluded.cost_usd,
            },
        )
    )
    await session.commit()


async def latest(
    session: AsyncSession, *, user_id: uuid.UUID, day: date | None = None
) -> DailyBrief | None:
    """The stored brief for a day, or the most recent one."""
    statement = select(DailyBrief).where(DailyBrief.user_id == user_id)
    if day is not None:
        statement = statement.where(DailyBrief.calendar_date == day)
    row: DailyBrief | None = await session.scalar(
        statement.order_by(DailyBrief.calendar_date.desc()).limit(1)
    )
    return row
