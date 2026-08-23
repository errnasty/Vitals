"""End-to-end request path: header → verification → allowlist → user row → response.

No Supabase project involved: tokens are minted locally with the same shape Supabase
issues, and verified by the same code that will verify the real ones.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support import EMAIL, SECRET, hs256
from vitals.db.session import get_session

ClientFactory = Callable[..., httpx.AsyncClient]


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, sessionmaker: async_sessionmaker[AsyncSession]
) -> ClientFactory:
    def factory(**env: str) -> httpx.AsyncClient:
        monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
        monkeypatch.setenv("VITALS_ALLOWED_EMAILS", EMAIL)
        for name, value in env.items():
            monkeypatch.setenv(name, value)

        from vitals.api.deps import get_verifier
        from vitals.api.main import create_app
        from vitals.config import get_settings

        get_settings.cache_clear()
        get_verifier.cache_clear()

        async def _session() -> AsyncIterator[AsyncSession]:
            async with sessionmaker() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_session] = _session
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return factory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_me_returns_the_user_and_the_token_it_proved(client: ClientFactory) -> None:
    async with client() as http:
        response = await http.get("/auth/me", headers=_auth(hs256()))

    body = response.json()
    assert response.status_code == 200
    assert body["email"] == EMAIL
    assert body["is_active"] is True
    assert body["timezone"] == "UTC"
    assert body["token"]["role"] == "authenticated"
    assert body["token"]["auth_methods"] == ["magiclink"]


async def test_missing_header_is_401_with_a_challenge(client: ClientFactory) -> None:
    async with client() as http:
        response = await http.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"] == "missing_credentials"
    assert 'error="missing_credentials"' in response.headers["www-authenticate"]


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic dXNlcjpwYXNz"},  # wrong scheme
        {"Authorization": "Bearer "},
    ],
)
async def test_bad_credentials_are_401(client: ClientFactory, header: dict[str, str]) -> None:
    async with client() as http:
        response = await http.get("/auth/me", headers=header)

    assert response.status_code == 401
    assert response.json()["error"] in {"invalid_token", "missing_credentials"}


async def test_expired_token_is_reported_distinctly(client: ClientFactory) -> None:
    """The frontend needs to tell 'sign in again' from 'you are not allowed here'."""
    now = int(time.time())
    async with client() as http:
        response = await http.get("/auth/me", headers=_auth(hs256(iat=now - 7200, exp=now - 3600)))

    assert response.status_code == 401
    assert response.json()["error"] == "token_expired"


async def test_another_account_is_403_not_401(client: ClientFactory) -> None:
    """An authentic Supabase token from someone else must not get in."""
    async with client() as http:
        response = await http.get("/auth/me", headers=_auth(hs256(email="stranger@example.com")))

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert "www-authenticate" not in response.headers


async def test_health_endpoints_stay_public(client: ClientFactory) -> None:
    """Railway's healthcheck has no token, and must never be locked out by auth."""
    async with client() as http:
        assert (await http.get("/livez")).status_code == 200


async def test_auth_can_be_switched_off_locally(client: ClientFactory) -> None:
    async with client(VITALS_AUTH_DISABLED="true") as http:
        response = await http.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == "dev@vitals.local"


async def test_the_app_refuses_to_start_unprotected_in_production(
    client: ClientFactory,
) -> None:
    from vitals.auth.policy import AuthNotReady

    with pytest.raises(AuthNotReady):
        client(ENVIRONMENT="production", VITALS_ALLOWED_EMAILS="")
