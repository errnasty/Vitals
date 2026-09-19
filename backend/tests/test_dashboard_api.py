"""The dashboard endpoints: one request per screen, everything already formatted.

The contract under test is the one the design system imposes — components take
formatted strings, never raw records — so these assert on the strings, not just on the
status code. A screen that has to decide how to render 26400 seconds is a screen doing
arithmetic, which is what this layer exists to prevent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.analytics import canonical as gold
from vitals.db.models import (
    AppUser,
    DerivedDaily,
    MetricDaily,
    ScoreContribution,
    ScorePillar,
    VitalsScore,
)
from vitals.db.session import get_session
from vitals.normalize import canonical as silver

ClientFactory = Callable[..., httpx.AsyncClient]

DAY = date(2026, 8, 21)


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


async def _seed(
    session: AsyncSession, *, days: int = 20, maker: async_sessionmaker | None = None
) -> None:
    """A user with a score, its pillars, a waterfall and the metrics behind it."""
    session.add(AppUser(id=USER_ID, email=EMAIL))
    await session.flush()

    for offset in range(days):
        day = DAY - timedelta(days=offset)
        session.add(
            VitalsScore(
                user_id=USER_ID,
                calendar_date=day,
                score=70.0 - offset * 0.5,
                coverage=0.95,
                trusted=True,
            )
        )
        session.add_all(
            [
                ScorePillar(
                    user_id=USER_ID,
                    calendar_date=day,
                    pillar=name,
                    score=value,
                    coverage=1.0,
                    weight=weight,
                )
                for name, value, weight in (
                    ("recovery", 69.0, 30),
                    ("sleep", 73.0, 25),
                    ("longevity", 100.0, 25),
                    ("training", 30.0, 20),
                )
            ]
        )

    session.add_all(
        [
            ScoreContribution(
                user_id=USER_ID,
                calendar_date=DAY,
                pillar="sleep",
                metric=gold.SLEEP_DURATION_7D,
                value=26400.0,
                points=78.0,
                weight=35,
                coverage=1.0,
                effect=6.81,
            ),
            ScoreContribution(
                user_id=USER_ID,
                calendar_date=DAY,
                pillar="recovery",
                metric=gold.TSB,
                value=-39.6,
                points=0.0,
                weight=30,
                coverage=1.0,
                effect=0.0,
            ),
        ]
    )

    session.add_all(
        [
            MetricDaily(
                user_id=USER_ID,
                metric=silver.SLEEP_DURATION,
                calendar_date=DAY,
                source="garmin",
                value=26400.0,
                unit="s",
            ),
            MetricDaily(
                user_id=USER_ID,
                metric=silver.RESTING_HR,
                calendar_date=DAY,
                source="garmin",
                value=48.0,
                unit="bpm",
            ),
        ]
    )
    for metric, value in (
        (gold.SLEEP_EFFICIENCY, 91.7),
        (gold.RHR_BASELINE, 48.5),
        (gold.WEIGHT_TREND, 72.48),
        (gold.WEIGHT_SLOPE, -0.17),
        (gold.CTL, 56.3),
        (gold.VO2MAX_TREND, 52.66),
    ):
        for offset in range(days):
            session.add(
                DerivedDaily(
                    user_id=USER_ID,
                    metric=metric,
                    calendar_date=DAY - timedelta(days=offset),
                    value=value,
                    unit=gold.unit_for(metric),
                    coverage=1.0,
                    inputs=10,
                )
            )
    await session.commit()


async def test_today_needs_a_token(client: ClientFactory) -> None:
    async with client() as http:
        response = await http.get("/today")
    assert response.status_code == 401


async def test_today_returns_the_whole_screen_in_one_request(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)

    async with client() as http:
        response = await http.get("/today", headers=_auth())

    body = response.json()
    assert response.status_code == 200
    assert body["date"] == "2026-08-21"
    assert body["score"]["display"] == "70"
    # The gauge draws this number as well as the arc, so it arrives already rounded.
    assert body["score"]["value"] == 70
    assert body["score"]["caption"] == "Balanced"
    assert body["score"]["rating"] == 2
    assert len(body["pillars"]) == 4
    assert len(body["trend"]) == 14


async def test_every_value_arrives_formatted(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """The screen must never have to turn 26400 into hours itself."""
    await _seed(pg_session)

    async with client() as http:
        body = (await http.get("/today", headers=_auth())).json()

    headlines = {item["key"]: item for item in body["headlines"]}
    assert headlines["sleep"]["value"] == "7h 20m"
    assert headlines["sleep"]["meta"] == "92% efficiency"
    assert headlines["resting_hr"]["value"] == "48"
    assert headlines["body"]["value"] == "72.5 kg"
    assert headlines["body"]["meta"] == "−0.17 kg / week"


async def test_an_empty_account_is_told_why_rather_than_shown_dashes(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """ "No data yet" and "something broke" must not look the same to a new user."""
    pg_session.add(AppUser(id=USER_ID, email=EMAIL))
    await pg_session.commit()

    async with client() as http:
        body = (await http.get("/today", headers=_auth())).json()

    assert body["score"] is None
    assert "connect Garmin" in body["empty_reason"]


async def test_silver_without_a_score_says_so_specifically(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    pg_session.add(AppUser(id=USER_ID, email=EMAIL))
    await pg_session.flush()
    pg_session.add(
        MetricDaily(
            user_id=USER_ID,
            metric=silver.STEPS,
            calendar_date=DAY,
            source="garmin",
            value=9000,
            unit="count",
        )
    )
    await pg_session.commit()

    async with client() as http:
        body = (await http.get("/today", headers=_auth())).json()

    assert "vitals score" in body["empty_reason"]


async def test_explain_returns_the_waterfall_biggest_first(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/explain", headers=_auth())).json()

    effects = [c["effect_value"] for c in body["contributions"]]
    assert effects == sorted(effects, reverse=True)

    sleep = next(c for c in body["contributions"] if c["metric"] == gold.SLEEP_DURATION_7D)
    assert sleep["value"] == "7h 20m"
    assert sleep["label"] == "Sleep duration"
    assert sleep["rationale"]


async def test_explain_404s_for_a_day_with_no_score(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)

    async with client() as http:
        response = await http.get("/score/explain?day=2020-01-01", headers=_auth())

    assert response.status_code == 404


async def test_trends_returns_the_score_and_the_series_behind_it(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)

    async with client() as http:
        body = (await http.get("/trends?days=14", headers=_auth())).json()

    assert body["days"] == 14
    assert len(body["score"]) == 14
    labels = {series["metric"]: series for series in body["series"]}
    assert labels[gold.CTL]["label"] == "Fitness"
    assert labels[gold.VO2MAX_TREND]["latest"] == "52.7 ml/kg/min"


async def test_trends_refuses_an_absurd_window(client: ClientFactory) -> None:
    async with client() as http:
        response = await http.get("/trends?days=9999", headers=_auth())
    assert response.status_code == 422


# ── the daily brief ─────────────────────────────────────────────────────────────


async def _seed_brief(session: AsyncSession, *, body: str = "Balanced today at 70.") -> None:
    from vitals.db.models import SOURCE_PYTHON, DailyBrief

    session.add(
        DailyBrief(
            user_id=USER_ID,
            calendar_date=DAY,
            body=body,
            source=SOURCE_PYTHON,
            model=None,
            digest_fingerprint="0" * 32,
            grounded=True,
            attempts=0,
            prompt_tokens=0,
            completion_tokens=0,
        )
    )
    await session.commit()


async def test_today_carries_the_brief_so_the_screen_is_still_one_round_trip(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)
    await _seed_brief(pg_session)

    async with client() as http:
        body = (await http.get("/today", headers=_auth())).json()

    assert body["brief"]["body"] == "Balanced today at 70."
    assert body["brief"]["written_by_model"] is False
    assert body["brief"]["date"] == DAY.isoformat()


async def test_today_without_a_brief_says_so_rather_than_failing(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """Nothing about the dashboard depends on a model having run."""
    await _seed(pg_session)

    async with client() as http:
        response = await http.get("/today", headers=_auth())

    assert response.status_code == 200
    assert response.json()["brief"] is None


async def test_the_brief_endpoint_reads_one_back(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)
    await _seed_brief(pg_session)

    async with client() as http:
        response = await http.get("/brief", headers=_auth())

    assert response.status_code == 200
    assert response.json()["source"] == "python"


async def test_a_day_with_no_brief_is_a_404_not_an_invention(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await _seed(pg_session)
    await _seed_brief(pg_session)

    async with client() as http:
        response = await http.get(
            "/brief", params={"day": (DAY - timedelta(days=3)).isoformat()}, headers=_auth()
        )

    assert response.status_code == 404


async def test_reading_the_brief_never_calls_a_model(
    client: ClientFactory, pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page load must not spend money or wait on a third party."""

    async def explode(
        self, url, **kwargs
    ):  # pragma: no cover - the assertion is that it never runs
        raise AssertionError("the API called a model")

    monkeypatch.setattr(httpx.AsyncClient, "post", explode)
    await _seed(pg_session)
    await _seed_brief(pg_session)

    async with client() as http:
        assert (await http.get("/today", headers=_auth())).status_code == 200
        assert (await http.get("/brief", headers=_auth())).status_code == 200
