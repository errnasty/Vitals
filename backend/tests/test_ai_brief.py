"""The brief's two promises: it always exists, and it is never stored ungrounded."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.ai import brief as ai
from vitals.ai import openrouter
from vitals.analytics import canonical as gold
from vitals.config import Settings
from vitals.db.models import (
    SOURCE_MODEL,
    SOURCE_PYTHON,
    DailyBrief,
    DerivedDaily,
    ScoreContribution,
    ScorePillar,
    VitalsScore,
)

DAY = date(2026, 9, 19)


def settings(**overrides) -> Settings:
    base = {"environment": "local", "auth_jwt_secret": "x" * 32, "openrouter_api_key": None}
    base.update(overrides)
    return Settings(**base)


def reply(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "anthropic/claude-sonnet-5",
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 40, "cost": 0.001},
        },
    )


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch):
    """A client whose answers are written in advance, recording what it was asked."""
    prompts: list[str] = []

    def install(*texts: str) -> list[str]:
        queue = list(texts)

        async def post(self, url, **kwargs):
            prompts.append(kwargs["json"]["messages"][-1]["content"])
            return reply(queue.pop(0))

        monkeypatch.setattr(httpx.AsyncClient, "post", post)
        monkeypatch.setattr(openrouter, "BACKOFF_S", (0.0, 0.0))
        return prompts

    return install


def client() -> openrouter.OpenRouter:
    return openrouter.OpenRouter(
        api_key="stub",
        base_url="https://stub/api/v1",
        model="anthropic/claude-sonnet-5",
        max_output_tokens=300,
        timeout_s=5.0,
    )


async def seed(session: AsyncSession, user_id: uuid.UUID, *, sleep_debt: float = 0.0) -> None:
    """One scored day with a fortnight of history behind it, as the engine would write it."""
    for offset in range(14, 0, -1):
        session.add(
            VitalsScore(
                id=uuid.uuid4(),
                user_id=user_id,
                calendar_date=DAY - timedelta(days=offset),
                score=81.0,
                coverage=0.94,
                trusted=True,
            )
        )
    session.add(
        VitalsScore(
            id=uuid.uuid4(),
            user_id=user_id,
            calendar_date=DAY,
            score=78.0,
            coverage=0.94,
            trusted=True,
        )
    )
    for name, value in (("recovery", 71.0), ("sleep", 73.0)):
        session.add(
            ScorePillar(
                id=uuid.uuid4(),
                user_id=user_id,
                calendar_date=DAY,
                pillar=name,
                score=value,
                coverage=1.0,
                weight=30.0,
            )
        )
    session.add(
        ScoreContribution(
            id=uuid.uuid4(),
            user_id=user_id,
            calendar_date=DAY,
            pillar="sleep",
            metric=gold.SLEEP_DURATION_7D,
            value=26160.0,
            points=76.0,
            weight=40.0,
            coverage=1.0,
            effect=6.6,
        )
    )
    if sleep_debt:
        session.add(
            DerivedDaily(
                id=uuid.uuid4(),
                user_id=user_id,
                metric=gold.SLEEP_DEBT,
                calendar_date=DAY,
                value=sleep_debt,
                unit="s",
                coverage=1.0,
                inputs=14,
            )
        )
    await session.commit()


async def stored(session: AsyncSession, user_id: uuid.UUID) -> DailyBrief:
    row = await session.scalar(select(DailyBrief).where(DailyBrief.user_id == user_id))
    assert row is not None
    return row


async def test_a_day_with_no_score_has_no_brief(pg_session, pg_user) -> None:
    assert await ai.generate(pg_session, user_id=pg_user.id, settings=settings()) is None


async def test_without_a_key_the_brief_is_composed_in_python(pg_session, pg_user) -> None:
    """The feature works with no model attached. That is the point of the fallback."""
    await seed(pg_session, pg_user.id, sleep_debt=5 * 3600.0)
    result = await ai.generate(pg_session, user_id=pg_user.id, settings=settings())

    assert result is not None
    assert result.source == SOURCE_PYTHON
    assert result.grounded
    assert "Balanced today at 78" in result.body
    assert "5h 0m" in result.body
    assert "OPENROUTER_API_KEY" in (result.fell_back or "")
    assert (await stored(pg_session, pg_user.id)).source == SOURCE_PYTHON


async def test_a_grounded_completion_is_stored_as_the_model_s(
    pg_session, pg_user, scripted
) -> None:
    await seed(pg_session, pg_user.id)
    scripted("Balanced today at 78, 3 below your 14-day mean of 81.")

    result = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())

    assert result is not None
    assert result.source == SOURCE_MODEL
    assert result.attempts == 1
    assert result.model == "anthropic/claude-sonnet-5"
    row = await stored(pg_session, pg_user.id)
    assert row.grounded and row.body == result.body
    assert row.prompt_tokens == 800 and row.cost_usd == pytest.approx(0.001)


async def test_an_ungrounded_completion_is_retried_with_the_fault_named(
    pg_session, pg_user, scripted
) -> None:
    await seed(pg_session, pg_user.id)
    prompts = scripted(
        "You slept 7.3 hours and had a Strong day.",
        "Balanced today at 78, 3 below your 14-day mean of 81.",
    )

    result = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())

    assert result is not None
    assert result.source == SOURCE_MODEL
    assert result.attempts == 2
    # A model that broke a rule it was already given needs to know which number it
    # invented, not the rule repeated.
    assert "7.3" in prompts[1]
    assert "Balanced" in prompts[1]
    # Both calls are accounted for, not just the one that worked.
    assert result.prompt_tokens == 1600


async def test_two_ungrounded_attempts_fall_back_rather_than_publish(
    pg_session, pg_user, scripted
) -> None:
    """A number Python did not compute never reaches the screen — not even flagged."""
    await seed(pg_session, pg_user.id)
    scripted("You slept 7.3 hours.", "Your score of 78.5 is Strong.")

    result = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())

    assert result is not None
    assert result.source == SOURCE_PYTHON
    assert "7.3" not in result.body and "78.5" not in result.body
    assert result.fell_back and "ungrounded" in result.fell_back
    row = await stored(pg_session, pg_user.id)
    assert row.source == SOURCE_PYTHON
    # The tokens were still spent, so they are still recorded.
    assert row.prompt_tokens == 1600
    assert row.attempts == 2


async def test_a_provider_failure_falls_back_rather_than_raising(
    pg_session, pg_user, monkeypatch
) -> None:
    """A daily brief that fails is not an incident. Tomorrow's runs anyway."""
    await seed(pg_session, pg_user.id)

    async def post(self, url, **kwargs):
        return httpx.Response(402, json={"error": {"message": "no credit remaining"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    result = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())

    assert result is not None
    assert result.source == SOURCE_PYTHON
    assert "no credit" in (result.fell_back or "")


async def test_an_unchanged_day_is_not_rewritten(pg_session, pg_user, scripted) -> None:
    """The cost control: a re-run over a day whose facts have not moved is free."""
    await seed(pg_session, pg_user.id)
    prompts = scripted("Balanced today at 78, 3 below your 14-day mean of 81.")

    first = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())
    second = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())

    assert first is not None and second is not None
    assert len(prompts) == 1
    assert second.reused and not first.reused
    assert second.body == first.body


async def test_a_changed_day_is_rewritten(pg_session, pg_user, scripted) -> None:
    await seed(pg_session, pg_user.id)
    prompts = scripted(
        "Balanced today at 78, 3 below your 14-day mean of 81.",
        "Balanced today at 78, 3 below your 14-day mean of 81. Sleep debt is 5h 0m.",
    )
    await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())

    pg_session.add(
        DerivedDaily(
            id=uuid.uuid4(),
            user_id=pg_user.id,
            metric=gold.SLEEP_DEBT,
            calendar_date=DAY,
            value=5 * 3600.0,
            unit="s",
            coverage=1.0,
            inputs=14,
        )
    )
    await pg_session.commit()

    again = await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())
    assert again is not None
    assert not again.reused
    assert len(prompts) == 2


async def test_force_rewrites_an_unchanged_day(pg_session, pg_user, scripted) -> None:
    """What you want after editing the prompt."""
    await seed(pg_session, pg_user.id)
    prompts = scripted(*["Balanced today at 78."] * 2)

    await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), client=client())
    result = await ai.generate(
        pg_session, user_id=pg_user.id, settings=settings(), client=client(), force=True
    )

    assert result is not None and not result.reused
    assert len(prompts) == 2


async def test_only_one_row_per_day_however_often_it_is_run(pg_session, pg_user) -> None:
    await seed(pg_session, pg_user.id)
    for _ in range(3):
        await ai.generate(pg_session, user_id=pg_user.id, settings=settings(), force=True)

    rows = (
        (await pg_session.execute(select(DailyBrief).where(DailyBrief.user_id == pg_user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_latest_reads_the_stored_brief_back(pg_session, pg_user) -> None:
    await seed(pg_session, pg_user.id)
    await ai.generate(pg_session, user_id=pg_user.id, settings=settings())

    row = await ai.latest(pg_session, user_id=pg_user.id)
    assert row is not None and row.calendar_date == DAY
    assert await ai.latest(pg_session, user_id=pg_user.id, day=DAY - timedelta(days=1)) is None


async def test_the_python_brief_never_invents_a_number(pg_session, pg_user) -> None:
    """It is assembled from sentences `signals.py` wrote, so it cannot drift."""
    from vitals.ai import grounding
    from vitals.ai.digest import load as load_digest

    await seed(pg_session, pg_user.id, sleep_debt=5 * 3600.0)
    digest = await load_digest(pg_session, user_id=pg_user.id)
    assert digest is not None
    assert grounding.check(ai.compose(digest), digest.render()).grounded
