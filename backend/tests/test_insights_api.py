"""The screen that has to be honest when it has nothing to say.

The empty case is the one worth testing hardest, because it is the normal one. What
matters is that it explains itself differently depending on *why* it is empty — too
little logged, or plenty logged and nothing found — and that a finding, when there is
one, arrives as a finished sentence rather than numbers for a browser to assemble.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.db.models import AppUser, DayContext, Insight
from vitals.db.session import get_session
from vitals.insights import engine
from vitals.normalize import canonical as silver

ClientFactory = Callable[..., httpx.AsyncClient]
TODAY = datetime.now(UTC).date()


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


async def _tag_days(session: AsyncSession, count: int) -> None:
    for offset in range(count):
        session.add(
            DayContext(
                user_id=USER_ID,
                calendar_date=TODAY - timedelta(days=offset),
                tag="alcohol",
            )
        )
    await session.commit()


async def _finding(session: AsyncSession, **overrides: object) -> None:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": USER_ID,
        "tag": "alcohol",
        "metric": silver.HRV_OVERNIGHT_AVG,
        "lag": 1,
        "n_with": 11,
        "n_without": 47,
        "mean_with": 42.0,
        "mean_without": 56.0,
        "delta": -14.0,
        "effect": -0.9,
        "p_value": 0.0004,
        "significant": True,
        "tested": 180,
        "window_start": TODAY - timedelta(days=400),
        "window_end": TODAY,
    }
    values.update(overrides)
    session.add(Insight(**values))  # type: ignore[arg-type]
    await session.commit()


async def test_it_requires_a_token(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        assert (await http.get("/insights")).status_code == 401


async def test_too_few_tagged_days_says_so_rather_than_showing_a_blank_page(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    await _tag_days(pg_session, 2)

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    assert body["findings"] == []
    assert body["tagged_days"] == 2
    assert str(engine.MIN_TAGGED_DAYS) in body["empty_reason"]
    # The number of days is the actionable part: it tells you how close you are.
    assert "tagged 2 days" in body["empty_reason"]


async def test_enough_days_and_nothing_found_is_a_different_sentence(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """Finding nothing is a result, and must not read like a missing feature."""
    await _tag_days(pg_session, engine.MIN_TAGGED_DAYS + 4)

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    assert body["findings"] == []
    assert "Nothing stood out" in body["empty_reason"]
    assert str(engine.MIN_TAGGED_DAYS) not in body["empty_reason"]


async def test_a_finding_arrives_as_a_finished_sentence(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """Every number in it is computed here. The browser assembles nothing."""
    await _tag_days(pg_session, 11)
    await _finding(pg_session)

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    (finding,) = body["findings"]
    # 14 / 56 = 25%, of the untagged baseline rather than of the tagged mean.
    assert finding["sentence"] == (
        "On days after alcohol, your overnight HRV is 25% lower the next day."
    )
    assert finding["change"] == "25% lower"
    assert finding["sample"] == "11 days with, 47 without"
    assert finding["confidence"] == "very consistent"
    assert body["empty_reason"] is None


async def test_the_denominator_is_reported_alongside_the_findings(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """One finding out of 180 tests is a different claim from one out of four."""
    await _tag_days(pg_session, 11)
    await _finding(pg_session)

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    assert body["tested"] == 180


async def test_a_finding_that_did_not_survive_the_correction_is_never_shown(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """The whole value of the correction is that it is applied before the screen."""
    await _tag_days(pg_session, 11)
    await _finding(pg_session, significant=False, p_value=0.04)

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    assert body["findings"] == []
    # Still counted, though: the run happened and its denominator is real.
    assert body["tested"] == 180


async def test_a_same_day_finding_does_not_claim_a_next_day_effect(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    await _tag_days(pg_session, 11)
    await _finding(pg_session, lag=0, metric=silver.SLEEP_SCORE, delta=-8.0, mean_without=80.0)

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    (finding,) = body["findings"]
    assert finding["when"] == "the same day"
    assert finding["sentence"] == ("On days with alcohol, your Garmin sleep score is 10% lower.")


async def test_a_tag_reads_as_prose_rather_than_as_its_column_heading(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """ "Stressful day" is a fine label and a broken sentence.

    Lowercasing the label is the obvious shortcut and it produces "on days with
    stressful day". Every tag carries its own mid-sentence wording for exactly this,
    and this screen is nothing but sentences.
    """
    await _tag_days(pg_session, 11)
    await _finding(
        pg_session,
        tag="stress",
        lag=0,
        metric=silver.RESTING_HR,
        delta=4.0,
        mean_without=54.0,
        n_with=18,
        n_without=44,
    )

    async with client() as http:
        body = (await http.get("/insights", headers=_auth())).json()

    (finding,) = body["findings"]
    assert finding["sentence"] == ("On days with stress, your resting heart rate is 7% higher.")
