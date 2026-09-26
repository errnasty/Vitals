"""The one place the user writes.

What is worth pinning down here is not that a tag round-trips, but the decisions:
that the vocabulary is closed, that unticking works, that context never reaches the
score, and that the note stays out of the analysis.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.db.models import AppUser, DayContext, DayNote
from vitals.db.session import get_session

ClientFactory = Callable[..., httpx.AsyncClient]


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


TODAY = datetime.now(UTC).date()


async def test_a_day_starts_empty_but_arrives_with_the_vocabulary(
    client: ClientFactory, user: AppUser
) -> None:
    """The client never keeps its own tag list, so a new tag appears the moment it
    appears in `context/canonical.py`."""
    async with client() as http:
        body = (await http.get("/context", headers=_auth())).json()

    assert body["tags"] == []
    assert body["note"] is None
    names = {t["name"] for t in body["vocabulary"]}
    assert {"alcohol", "stress", "illness"} <= names
    # Alcohol is the one tag that carries an amount.
    alcohol = next(t for t in body["vocabulary"] if t["name"] == "alcohol")
    assert alcohol["magnitude"] == "drinks"
    assert next(t for t in body["vocabulary"] if t["name"] == "stress")["magnitude"] is None


async def test_tags_round_trip_with_their_magnitude(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        written = await http.put(
            "/context/tags",
            json={"tags": [{"name": "alcohol", "magnitude": 4}, {"name": "late_meal"}]},
            headers=_auth(),
        )
        read = await http.get("/context", headers=_auth())

    for body in (written.json(), read.json()):
        tags = {t["name"]: t["magnitude"] for t in body["tags"]}
        assert tags == {"alcohol": 4, "late_meal": None}


async def test_unticking_a_tag_removes_it(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """The screen sends the whole day, so a write replaces rather than merges —
    otherwise nothing could ever be unticked."""
    async with client() as http:
        await http.put(
            "/context/tags",
            json={"tags": [{"name": "alcohol", "magnitude": 2}, {"name": "stress"}]},
            headers=_auth(),
        )
        body = (
            await http.put("/context/tags", json={"tags": [{"name": "stress"}]}, headers=_auth())
        ).json()

    assert [t["name"] for t in body["tags"]] == ["stress"]
    rows = (await pg_session.execute(select(DayContext))).scalars().all()
    assert len(rows) == 1


async def test_a_tag_outside_the_vocabulary_is_refused(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """Free text cannot be correlated against anything, which is the whole reason
    the list is closed."""
    async with client() as http:
        response = await http.put(
            "/context/tags", json={"tags": [{"name": "had a few beers"}]}, headers=_auth()
        )

    assert response.status_code == 422
    assert "not a known tag" in response.json()["detail"]


async def test_one_bad_tag_writes_none_of_them(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    """Validated before anything is written, so a rejected request leaves no half-day."""
    async with client() as http:
        await http.put(
            "/context/tags",
            json={"tags": [{"name": "stress"}, {"name": "vibes"}]},
            headers=_auth(),
        )

    assert (await pg_session.execute(select(DayContext))).scalars().all() == []


async def test_a_note_is_stored_and_cleared(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession
) -> None:
    async with client() as http:
        body = (
            await http.put(
                "/context/note", json={"note": "  flight home, slept badly  "}, headers=_auth()
            )
        ).json()
        assert body["note"] == "flight home, slept badly"

        cleared = (await http.put("/context/note", json={"note": "   "}, headers=_auth())).json()

    assert cleared["note"] is None
    # Cleared means gone, not an empty string sitting in the table.
    assert (await pg_session.execute(select(DayNote))).scalars().all() == []


async def test_the_future_cannot_be_tagged(client: ClientFactory, user: AppUser) -> None:
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    async with client() as http:
        response = await http.put(
            "/context/tags", params={"day": tomorrow}, json={"tags": []}, headers=_auth()
        )

    assert response.status_code == 400
    assert "has not happened yet" in response.json()["detail"]


async def test_the_distant_past_is_refused(client: ClientFactory, user: AppUser) -> None:
    """Not a storage limit — a guard against a fat-fingered URL writing to 1970."""
    long_ago = (TODAY - timedelta(days=400)).isoformat()
    async with client() as http:
        response = await http.get("/context", params={"day": long_ago}, headers=_auth())

    assert response.status_code == 400


async def test_yesterday_can_still_be_filled_in(client: ClientFactory, user: AppUser) -> None:
    """This gets filled in at 11pm or the morning after, so backdating has to work."""
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    async with client() as http:
        body = (
            await http.put(
                "/context/tags",
                params={"day": yesterday},
                json={"tags": [{"name": "travel"}]},
                headers=_auth(),
            )
        ).json()

    assert body["date"] == yesterday
    assert [t["name"] for t in body["tags"]] == ["travel"]


async def test_context_needs_a_token(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        assert (await http.get("/context")).status_code == 401
        assert (await http.put("/context/tags", json={"tags": []})).status_code == 401
