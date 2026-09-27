"""The coach endpoint: finished values, and an honest empty state.

Early on this screen has almost nothing — no anchors, no findings, no experiment —
and that is the state most worth getting right, because it is the state a new account
lives in for weeks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.analytics import canonical as gold
from vitals.db.models import AppUser, ResponseTrait, ScoreContribution, VitalsScore
from vitals.db.session import get_session
from vitals.normalize import canonical as silver
from vitals.profile import canonical as traits

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


async def test_it_requires_a_token(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        assert (await http.get("/coach")).status_code == 401


async def test_a_fresh_account_gets_an_empty_coach_not_an_error(
    client: ClientFactory, user: AppUser
) -> None:
    async with client() as http:
        body = (await http.get("/coach", headers=_auth())).json()

    assert body["interventions"] == []
    assert body["profile"]["traits"] == []
    assert body["profile"]["zones"] == []
    assert body["experiment"] is None
    assert "None of it is medical advice" in body["caveat"]


async def test_points_are_worded_here_so_no_screen_rounds_a_score(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    pg_session.add(
        VitalsScore(user_id=USER_ID, calendar_date=DAY, score=70.0, coverage=0.9, trusted=True)
    )
    pg_session.add(
        ScoreContribution(
            user_id=USER_ID,
            calendar_date=DAY,
            pillar="sleep",
            metric=gold.SLEEP_CONSISTENCY,
            value=1.0,
            points=40.0,
            weight=25.0,
            coverage=1.0,
            effect=4.0,
            headroom=6.3,
        )
    )
    await pg_session.commit()

    async with client() as http:
        body = (await http.get("/coach", headers=_auth())).json()

    (item,) = body["interventions"]
    assert item["worth"] == "worth up to 6 points"
    assert item["label"] == "Sleep regularity"


async def test_zones_appear_only_once_a_maximum_has_been_measured(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """220-minus-age is a number that looks precise and is not, so there is no
    fallback: without the measurement there are no zones."""
    pg_session.add(
        ResponseTrait(
            user_id=USER_ID,
            trait=traits.MAX_HR,
            value=190.0,
            unit="bpm",
            observations=340,
            basis="the highest heart rate in 340 recorded activities",
        )
    )
    await pg_session.commit()

    async with client() as http:
        body = (await http.get("/coach", headers=_auth())).json()

    zones = body["profile"]["zones"]
    assert len(zones) == 5
    assert zones[0]["band"] == "95–114 bpm"
    assert zones[-1]["band"] == "171–190 bpm"
    assert body["profile"]["traits"][0]["observations"] == 340


async def test_starting_an_experiment_records_the_question(
    client: ClientFactory, user: AppUser
) -> None:
    async with client() as http:
        response = await http.post(
            "/coach/experiment",
            json={"tag": "alcohol", "metric": silver.HRV_OVERNIGHT_AVG, "lag": 1, "days": 21},
            headers=_auth(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["tag_label"] == "Alcohol"
    assert "before the days start" in body["hypothesis"]
    assert body["conclusion"] is None


async def test_an_experiment_about_something_unloggable_is_refused(
    client: ClientFactory, user: AppUser
) -> None:
    async with client() as http:
        response = await http.post(
            "/coach/experiment",
            json={"tag": "sunspots", "metric": silver.HRV_OVERNIGHT_AVG},
            headers=_auth(),
        )

    assert response.status_code == 422
    assert "sunspots" in response.json()["detail"]


async def test_an_experiment_about_a_metric_it_cannot_phrase_is_refused(
    client: ClientFactory, user: AppUser
) -> None:
    """A hypothesis it cannot write is a hypothesis nobody can read afterwards."""
    async with client() as http:
        response = await http.post(
            "/coach/experiment",
            json={"tag": "alcohol", "metric": "wrist_temperature_at_dawn"},
            headers=_auth(),
        )

    assert response.status_code == 422


async def test_the_days_left_count_down(client: ClientFactory, user: AppUser) -> None:
    from vitals.coach import experiments

    async with client() as http:
        await http.post(
            "/coach/experiment",
            json={"tag": "alcohol", "metric": silver.HRV_OVERNIGHT_AVG, "days": 21},
            headers=_auth(),
        )
        body = (await http.get("/coach", headers=_auth())).json()

    assert body["experiment"]["days_left"] == 20
    assert experiments.DEFAULT_DAYS == 21


async def test_two_differently_ranked_lines_do_not_claim_the_same_worth(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """Python rounds 6.5 to 6, not 7 — round-half-even.

    Right for statistics, wrong for a ranked list: 6.5 and 5.8 both rendered as
    "6 points", so the top two lines claimed the same value while being in a
    deliberate order.
    """
    pg_session.add(
        VitalsScore(user_id=USER_ID, calendar_date=DAY, score=70.0, coverage=0.9, trusted=True)
    )
    for metric, headroom in ((gold.CTL, 6.5), (gold.SLEEP_DEBT, 5.8)):
        pg_session.add(
            ScoreContribution(
                user_id=USER_ID,
                calendar_date=DAY,
                pillar="training" if metric == gold.CTL else "sleep",
                metric=metric,
                value=1.0,
                points=40.0,
                weight=25.0,
                coverage=1.0,
                effect=4.0,
                headroom=headroom,
            )
        )
    await pg_session.commit()

    async with client() as http:
        body = (await http.get("/coach", headers=_auth())).json()

    worths = [item["worth"] for item in body["interventions"]]
    assert worths == ["worth up to 7 points", "worth up to 6 points"]


async def test_a_measured_anchor_carries_its_unit(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """ "Maximum heart rate: 188" beside "Nightly sleep need: 7h 30m" reads as though
    one of them forgot its unit."""
    pg_session.add(
        ResponseTrait(
            user_id=USER_ID,
            trait=traits.MAX_HR,
            value=188.0,
            unit="bpm",
            observations=412,
            basis="the highest heart rate in 412 recorded activities",
        )
    )
    pg_session.add(
        ResponseTrait(
            user_id=USER_ID,
            trait=traits.SLEEP_NEED,
            value=27000.0,
            unit="s",
            observations=412,
            basis="your next-day HRV is highest after 7-8 hours",
        )
    )
    await pg_session.commit()

    async with client() as http:
        body = (await http.get("/coach", headers=_auth())).json()

    values = {row["trait"]: row["value"] for row in body["profile"]["traits"]}
    assert values[traits.MAX_HR] == "188 bpm"
    assert values[traits.SLEEP_NEED] == "7h 30m"
