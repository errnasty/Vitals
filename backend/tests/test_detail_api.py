"""The screens that answer "why is this number what it is, and what would change it".

The interesting assertions are about honesty rather than plumbing: that the target a
screen shows is the one the score actually used, that a reading nobody controls is
never dressed up as a goal, and that "what would help" is ranked by points recoverable
rather than by what happens to have scored worst.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.analytics import canonical as gold
from vitals.db.models import AppUser, ScoreContribution, ScorePillar, VitalsScore
from vitals.db.session import get_session

ClientFactory = Callable[..., httpx.AsyncClient]

DAY = date(2026, 9, 19)


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


def contribution(
    pillar: str, metric: str, *, value: float, points: float, effect: float, headroom: float
) -> ScoreContribution:
    return ScoreContribution(
        user_id=USER_ID,
        calendar_date=DAY,
        pillar=pillar,
        metric=metric,
        value=value,
        points=points,
        weight=35.0,
        coverage=1.0,
        effect=effect,
        headroom=headroom,
    )


async def seed(session: AsyncSession) -> None:
    session.add(AppUser(id=USER_ID, email=EMAIL))
    await session.flush()
    session.add(
        VitalsScore(user_id=USER_ID, calendar_date=DAY, score=78.0, coverage=0.94, trusted=True)
    )
    session.add_all(
        [
            ScorePillar(
                user_id=USER_ID, calendar_date=DAY, pillar=name, score=s, coverage=1.0, weight=w
            )
            for name, s, w in (
                ("recovery", 71.0, 30.0),
                ("sleep", 73.0, 25.0),
                ("longevity", 100.0, 25.0),
                ("training", 68.0, 20.0),
            )
        ]
    )
    session.add_all(
        [
            # A ramp with room to improve, and the biggest gain on the board.
            contribution(
                "sleep", gold.SLEEP_DEBT, value=7 * 3600.0, points=44.0, effect=2.7, headroom=3.5
            ),
            # A ramp already at full marks.
            contribution(
                "sleep", gold.SLEEP_EFFICIENCY, value=96.0, points=100.0, effect=3.8, headroom=0.0
            ),
            # A reading nobody controls.
            contribution(
                "recovery", gold.HRV_DEVIATION, value=0.05, points=82.0, effect=9.8, headroom=2.2
            ),
            # Scored worst of all, but worth almost nothing.
            contribution(
                "training", gold.MONOTONY, value=2.4, points=7.0, effect=0.1, headroom=0.2
            ),
            # A band, sitting inside it.
            contribution("training", gold.ACWR, value=1.1, points=100.0, effect=7.0, headroom=0.0),
        ]
    )
    await session.commit()


def _by_metric(factors: list[dict], metric: str) -> dict:
    return next(f for f in factors if f["metric"] == metric)


# ── the pillar screen ───────────────────────────────────────────────────────────


async def test_a_pillar_shows_what_it_is_made_of(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/pillar/sleep", headers=_auth())).json()

    pillar = body["pillar"]
    assert pillar["label"] == "Sleep"
    assert pillar["display"] == "73"
    assert pillar["weight"] == "25%"
    assert pillar["summary"]
    assert {f["metric"] for f in pillar["factors"]} == {
        gold.SLEEP_DEBT,
        gold.SLEEP_EFFICIENCY,
    }


async def test_the_target_is_the_one_the_score_actually_used(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """The app grades sleep debt against 0, so 0 is what it must be able to show."""
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/pillar/sleep", headers=_auth())).json()

    debt = _by_metric(body["pillar"]["factors"], gold.SLEEP_DEBT)
    assert debt["target"] == "0m"
    assert debt["scale"] == "14h 0m scores 0, 0m scores 100"
    assert debt["basis"] == "lower is better, down to the anchor"


async def test_a_reading_nobody_controls_is_never_given_a_target(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """ "Get your overnight HRV to +0.5 SD" is not advice; it is a number you do not
    control, and presenting it as a goal teaches the wrong thing."""
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/pillar/recovery", headers=_auth())).json()

    hrv = _by_metric(body["pillar"]["factors"], gold.HRV_DEVIATION)
    assert hrv["target"] is None
    assert hrv["advice"] is not None
    assert "not something to aim at" in hrv["advice"].lower()
    # The value still carries its unit, so nobody reads the z-score as an HRV.
    assert "SD" in hrv["value"]


async def test_a_line_at_full_marks_is_told_nothing(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/pillar/sleep", headers=_auth())).json()

    assert _by_metric(body["pillar"]["factors"], gold.SLEEP_EFFICIENCY)["advice"] is None


async def test_sitting_inside_a_band_earns_no_nudge(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """Telling someone where they should be to move is advice invented by the screen."""
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/pillar/training", headers=_auth())).json()

    acwr = _by_metric(body["pillar"]["factors"], gold.ACWR)
    assert acwr["advice"] is None
    assert acwr["basis"].startswith("best inside a range")
    assert acwr["target"] == "0.80–1.30"


async def test_an_unknown_pillar_is_a_404(client: ClientFactory, pg_session: AsyncSession) -> None:
    await seed(pg_session)

    async with client() as http:
        assert (await http.get("/score/pillar/vibes", headers=_auth())).status_code == 404


# ── the score screen ────────────────────────────────────────────────────────────


async def test_the_score_screen_explains_how_it_is_built(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/detail", headers=_auth())).json()

    assert body["display"] == "78"
    assert body["caption"] == "Balanced"
    assert len(body["method"]["steps"]) >= 3
    assert "50%" in body["method"]["coverage_floor"]
    assert [p["name"] for p in body["pillars"]] == [
        "recovery",
        "sleep",
        "longevity",
        "training",
    ]


async def test_opportunities_rank_by_points_recoverable_not_by_worst_score(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    """Monotony scored 7 — far worse than anything else — and is worth 0.2 points.
    Sending someone to fix that instead of their sleep debt would be wrong."""
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/detail", headers=_auth())).json()

    ranked = [f["metric"] for f in body["opportunities"]]
    assert ranked[0] == gold.SLEEP_DEBT
    # Below the threshold, so not worth anyone's attention at all.
    assert gold.MONOTONY not in ranked


async def test_opportunities_leave_out_what_is_already_done(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await seed(pg_session)

    async with client() as http:
        body = (await http.get("/score/detail", headers=_auth())).json()

    assert gold.SLEEP_EFFICIENCY not in [f["metric"] for f in body["opportunities"]]


async def test_the_detail_screens_need_a_token(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await seed(pg_session)

    async with client() as http:
        assert (await http.get("/score/detail")).status_code == 401
        assert (await http.get("/score/pillar/sleep")).status_code == 401


async def test_a_day_with_no_score_is_a_404(
    client: ClientFactory, pg_session: AsyncSession
) -> None:
    await seed(pg_session)

    async with client() as http:
        response = await http.get("/score/detail", params={"day": "2020-01-01"}, headers=_auth())

    assert response.status_code == 404
