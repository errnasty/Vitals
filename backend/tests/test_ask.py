"""Answering a question, and refusing to answer it from anything but the data.

The tests that matter are the ones about what does *not* reach the model: a note
nobody opted into sharing, and a number the model invented. Both are failures that
look like success on screen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.ai import ask as ask_engine
from vitals.ai import context
from vitals.analytics import canonical as gold
from vitals.db.models import AppUser, DayNote, ScoreContribution, VitalsScore
from vitals.db.session import get_session

ClientFactory = Callable[..., httpx.AsyncClient]
DAY = date(2026, 9, 1)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, pg_session: AsyncSession) -> ClientFactory:
    def factory() -> httpx.AsyncClient:
        monkeypatch.setenv("VITALS_AUTH_JWT_SECRET", SECRET)
        monkeypatch.setenv("VITALS_ALLOWED_EMAILS", EMAIL)

        from vitals.api.deps import get_verifier
        from vitals.api.main import create_app
        from vitals.config import get_settings

        get_settings.cache_clear()
        get_verifier.cache_clear()

        async def _session() -> AsyncIterator[AsyncSession]:
            yield pg_session

        app = create_app()
        app.dependency_overrides[get_session] = _session
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return factory


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {hs256()}"}


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


async def _score(session: AsyncSession, day: date = DAY) -> None:
    session.add(
        VitalsScore(user_id=USER_ID, calendar_date=day, score=78.0, coverage=0.92, trusted=True)
    )
    session.add(
        ScoreContribution(
            user_id=USER_ID,
            calendar_date=day,
            pillar="sleep",
            metric=gold.SLEEP_DEBT,
            value=25000.0,
            points=44.0,
            weight=25.0,
            coverage=1.0,
            effect=4.4,
            headroom=5.6,
        )
    )
    await session.commit()


# ── routing ─────────────────────────────────────────────────────────────────────


def test_a_question_routes_to_the_parts_it_mentions() -> None:
    assert "patterns" in context.route("does alcohol affect my sleep?")
    assert "similar" in context.route("have I had a day like this before?")
    assert "coach" in context.route("what should I do about it")


def test_every_question_gets_the_day_itself() -> None:
    """A question about anything is a question about a day, and the fallback when
    nothing matches has to be useful rather than empty."""
    assert context.route("hmm") == ("score",)


def test_routing_is_not_a_model_s_decision() -> None:
    """A model choosing its own retrieval can choose to fetch nothing and answer from
    memory, which on health data is the failure that matters."""
    assert context.route("how did I sleep?") == context.route("HOW DID I SLEEP?")


# ── the pack ────────────────────────────────────────────────────────────────────


async def test_the_pack_carries_the_numbers_the_answer_may_use(
    pg_session: AsyncSession, user: AppUser
) -> None:
    await _score(pg_session)

    pack = await context.build(pg_session, user_id=USER_ID, question="how is my score?", today=DAY)

    rendered = pack.render()
    assert "78" in rendered
    assert "Sleep debt" in rendered
    assert pack.day == DAY


async def test_data_older_than_it_looks_says_so(pg_session: AsyncSession, user: AppUser) -> None:
    """An answer written confidently about "today" from a week-old sync is the single
    most misleading thing this feature could do."""
    note = context.stale(DAY, DAY + timedelta(days=6))

    assert note is not None and "6 days ago" in note
    assert context.stale(DAY, DAY) is None


# ── the promise ─────────────────────────────────────────────────────────────────


async def test_a_note_is_never_sent_unless_it_was_allowed(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The Log screen promised this on the screen where the text was typed."""
    await _score(pg_session)
    pg_session.add(
        DayNote(user_id=USER_ID, calendar_date=DAY, body="felt awful, argued with my brother")
    )
    await pg_session.commit()

    pack = await context.build(
        pg_session, user_id=USER_ID, question="why do I feel bad?", today=DAY
    )

    assert "argued" not in pack.render()
    assert "brother" not in pack.render()


async def test_a_note_is_sent_once_it_is_allowed(pg_session: AsyncSession, user: AppUser) -> None:
    await _score(pg_session)
    pg_session.add(DayNote(user_id=USER_ID, calendar_date=DAY, body="slept in the spare room"))
    user.share_notes_with_ai = True
    await pg_session.commit()

    pack = await context.build(
        pg_session, user_id=USER_ID, question="why do I feel bad?", today=DAY
    )

    assert "spare room" in pack.render()


async def test_the_setting_defaults_to_the_promise_that_was_made(
    client: ClientFactory, user: AppUser
) -> None:
    async with client() as http:
        body = (await http.get("/ask/settings", headers=_auth())).json()

    assert body["share_notes_with_ai"] is False
    assert "not shown to a model" in body["explanation"]


async def test_turning_it_on_changes_what_the_screen_says(
    client: ClientFactory, user: AppUser
) -> None:
    """The wording moves with the behaviour rather than staying reassuring."""
    async with client() as http:
        body = (
            await http.put("/ask/settings", json={"share_notes_with_ai": True}, headers=_auth())
        ).json()

    assert body["share_notes_with_ai"] is True
    assert "not shown to a model" not in body["explanation"]
    assert "only read" in body["explanation"]


# ── answering ───────────────────────────────────────────────────────────────────


async def test_with_no_api_key_the_facts_themselves_are_the_answer(
    pg_session: AsyncSession, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not an apology and not an error — for most questions this is what was wanted."""
    from vitals.config import get_settings

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    await _score(pg_session)

    answer = await ask_engine.answer(
        pg_session, user_id=USER_ID, question="how is my sleep?", today=DAY
    )

    assert answer.source == ask_engine.SOURCE_PYTHON
    assert "78" in answer.text
    assert answer.note is not None


async def test_an_empty_question_is_refused(pg_session: AsyncSession, user: AppUser) -> None:
    with pytest.raises(ask_engine.TooLong):
        await ask_engine.answer(pg_session, user_id=USER_ID, question="   ")


async def test_a_question_longer_than_an_answer_is_refused(
    pg_session: AsyncSession, user: AppUser
) -> None:
    with pytest.raises(ask_engine.TooLong):
        await ask_engine.answer(pg_session, user_id=USER_ID, question="x" * 900)


async def test_the_endpoint_requires_a_token(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        assert (await http.post("/ask", json={"question": "hi"})).status_code == 401


async def test_an_account_with_no_data_says_so_rather_than_guessing(
    pg_session: AsyncSession, user: AppUser
) -> None:
    answer = await ask_engine.answer(
        pg_session, user_id=USER_ID, question="how am I doing?", today=DAY
    )

    assert "No score has been computed yet." in answer.text


async def test_another_account_s_days_are_never_reachable(
    pg_session: AsyncSession, user: AppUser
) -> None:
    other = uuid.uuid4()
    pg_session.add(AppUser(id=other, email="other@example.com"))
    await pg_session.commit()
    await _score(pg_session)

    pack = await context.build(pg_session, user_id=other, question="how is my score?", today=DAY)

    assert "78" not in pack.render()
