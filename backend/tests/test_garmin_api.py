"""Connecting Garmin from the app — the endpoints, and the guards that make them safe.

These run entirely against a stubbed `begin_login`/`finish_login`, so nothing here
touches Garmin. What is being tested is everything *around* the login: that the
half-finished state survives between two requests, that it expires, that a rejected
code cannot be retried forever, and that neither secret is ever written down where it
should not be.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, SECRET, USER_ID, hs256
from vitals.api.routers import garmin as router
from vitals.db.models import (
    GARMIN_LOGIN_ATTEMPTS,
    GARMIN_PENDING_LOGIN,
    GARMIN_TOKENS,
    AppUser,
    Credential,
    SourceConnection,
)
from vitals.db.session import get_session
from vitals.sources.garmin import MFARequired, NeedsReauth, RateLimited

ClientFactory = Callable[..., httpx.AsyncClient]

GARMIN_EMAIL = "athlete@garmin.example"
PASSWORD = "correct horse battery staple"
TOKENS = '{"oauth1": "a", "oauth2": "b"}'
STATE = {"ticket": "abc123", "csrf": "xyz"}


class FakeClient:
    """Stands in for a logged-in `GarminClient`."""

    display_name = "Athlete"

    def export_tokens(self) -> str:
        return TOKENS


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, pg_session: AsyncSession) -> ClientFactory:
    def factory() -> httpx.AsyncClient:
        monkeypatch.setenv("VITALS_AUTH_JWT_SECRET", SECRET)
        monkeypatch.setenv("VITALS_ALLOWED_EMAILS", EMAIL)
        monkeypatch.setenv("VITALS_ENCRYPTION_KEY", _fernet_key())

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


def _fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


async def _noop_pull(user_id: uuid.UUID) -> None:
    """The history pull has its own tests; these are about the connection state."""


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {hs256()}"}


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


def stub_begin(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[tuple[str, str]]:
    """Replace the SSO call, recording what it was asked to log in as."""
    calls: list[tuple[str, str]] = []

    async def begin(email: str, password: str, **kwargs: Any) -> Any:
        calls.append((email, password))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(router, "begin_login", begin)
    return calls


def stub_finish(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def finish(
        email: str, password: str, state: dict[str, Any], code: str, **kwargs: Any
    ) -> Any:
        calls.append({"email": email, "password": password, "state": state, "code": code})
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(router, "finish_login", finish)
    return calls


async def _credential(session: AsyncSession, name: str) -> Credential | None:
    return await session.scalar(
        select(Credential).where(Credential.user_id == USER_ID, Credential.name == name)
    )


# ── status ──────────────────────────────────────────────────────────────────────


async def test_status_is_disconnected_before_anything_happens(
    client: ClientFactory, user: AppUser
) -> None:
    async with client() as http:
        body = (await http.get("/garmin/status", headers=_auth())).json()

    assert body == {
        "connected": False,
        "state": "disconnected",
        "detail": None,
        "awaiting_mfa": False,
        "last_success_at": None,
        "locked_until": None,
        # Nothing stored, so signing in is genuinely the next step.
        "needs_login": True,
        "trouble": None,
        # No history has been asked for, so there is nothing to report on it.
        "history": None,
    }


async def test_the_endpoints_require_a_token(client: ClientFactory, user: AppUser) -> None:
    """A connect endpoint anyone can POST to is a way to spend someone else's account."""
    async with client() as http:
        for method, path in (
            ("GET", "/garmin/status"),
            ("POST", "/garmin/connect"),
            ("POST", "/garmin/connect/mfa"),
            ("POST", "/garmin/disconnect"),
        ):
            response = await http.request(method, path, json={})
            assert response.status_code == 401, path


# ── the happy paths ─────────────────────────────────────────────────────────────


async def test_a_login_without_mfa_connects_in_one_request(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    calls = stub_begin(monkeypatch, FakeClient())

    async with client() as http:
        response = await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert response.json()["display_name"] == "Athlete"
    assert calls == [(GARMIN_EMAIL, PASSWORD)]

    assert await _credential(pg_session, GARMIN_TOKENS) is not None
    connection = await pg_session.scalar(
        select(SourceConnection).where(SourceConnection.user_id == USER_ID)
    )
    assert connection is not None and connection.status == "active"


async def test_an_mfa_login_survives_between_two_requests(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """The whole reason this exists: the code arrives in a *later* request."""
    stub_begin(monkeypatch, MFARequired(client_state=STATE))

    async with client() as http:
        first = await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        assert first.json()["status"] == "mfa_required"
        assert (await http.get("/garmin/status", headers=_auth())).json()["awaiting_mfa"] is True

        # Nothing is held in memory — the state is in the database, encrypted.
        row = await _credential(pg_session, GARMIN_PENDING_LOGIN)
        assert row is not None
        assert PASSWORD not in row.ciphertext
        assert "ticket" not in row.ciphertext

        finished = stub_finish(monkeypatch, FakeClient())
        second = await http.post("/garmin/connect/mfa", json={"code": " 123456 "}, headers=_auth())

    assert second.status_code == 200
    assert second.json()["status"] == "connected"
    # The resume gets exactly what the first request stored, and a trimmed code.
    assert finished == [
        {"email": GARMIN_EMAIL, "password": PASSWORD, "state": STATE, "code": "123456"}
    ]
    assert await _credential(pg_session, GARMIN_TOKENS) is not None


async def test_a_finished_login_leaves_no_password_behind(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """The pending record holds the password for minutes. Success ends that."""
    stub_begin(monkeypatch, MFARequired(client_state=STATE))
    stub_finish(monkeypatch, FakeClient())

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        await http.post("/garmin/connect/mfa", json={"code": "123456"}, headers=_auth())

    assert await _credential(pg_session, GARMIN_PENDING_LOGIN) is None


# ── the guards ──────────────────────────────────────────────────────────────────


async def test_bad_credentials_are_a_401_carrying_garmin_s_own_words(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    stub_begin(monkeypatch, NeedsReauth("Garmin rejected the credentials: bad password"))

    async with client() as http:
        response = await http.post(
            "/garmin/connect", json={"email": GARMIN_EMAIL, "password": "wrong"}, headers=_auth()
        )

    assert response.status_code == 401
    assert "rejected the credentials" in response.json()["detail"]


async def test_repeated_failures_close_the_door(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    """Every attempt is a real SSO request from a datacenter IP. That is the risk."""
    stub_begin(monkeypatch, NeedsReauth("nope"))

    async with client() as http:
        for _ in range(router.MAX_ATTEMPTS):
            assert (
                await http.post(
                    "/garmin/connect",
                    json={"email": GARMIN_EMAIL, "password": "wrong"},
                    headers=_auth(),
                )
            ).status_code == 401

        locked = await http.post(
            "/garmin/connect", json={"email": GARMIN_EMAIL, "password": PASSWORD}, headers=_auth()
        )
        status_body = (await http.get("/garmin/status", headers=_auth())).json()

    assert locked.status_code == 429
    assert "too many failed attempts" in locked.json()["detail"]
    assert status_body["locked_until"] is not None


async def test_a_lockout_blocks_the_mfa_step_too(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    stub_begin(monkeypatch, MFARequired(client_state=STATE))
    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )

        from vitals.config import get_settings
        from vitals.security.vault import build_vault

        vault = build_vault(pg_session, get_settings())
        await vault.put(
            USER_ID,
            GARMIN_LOGIN_ATTEMPTS,
            json.dumps(
                {
                    "failures": router.MAX_ATTEMPTS,
                    "locked_until": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                }
            ),
        )

        response = await http.post("/garmin/connect/mfa", json={"code": "123456"}, headers=_auth())

    assert response.status_code == 429


async def test_a_rejected_code_cannot_be_retried_against_the_same_state(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """Garmin will not take a second code against a rejected one — say so and reset."""
    stub_begin(monkeypatch, MFARequired(client_state=STATE))
    stub_finish(monkeypatch, NeedsReauth("Garmin rejected the code: expired"))

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        first = await http.post("/garmin/connect/mfa", json={"code": "000000"}, headers=_auth())
        second = await http.post("/garmin/connect/mfa", json={"code": "111111"}, headers=_auth())

    assert first.status_code == 401
    # The state is gone, so the second attempt has nothing to resume — a clear
    # "start again" rather than a loop that can never succeed.
    assert second.status_code == 409
    assert await _credential(pg_session, GARMIN_PENDING_LOGIN) is None


async def test_a_pending_login_expires(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """A password sitting in the database for the afternoon is not the deal."""
    stub_begin(monkeypatch, MFARequired(client_state=STATE))
    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )

        from vitals.config import get_settings
        from vitals.security.vault import build_vault

        vault = build_vault(pg_session, get_settings())
        raw = await vault.get(USER_ID, GARMIN_PENDING_LOGIN)
        assert raw is not None
        record = json.loads(raw)
        record["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        await vault.put(USER_ID, GARMIN_PENDING_LOGIN, json.dumps(record))

        response = await http.post("/garmin/connect/mfa", json={"code": "123456"}, headers=_auth())
        awaiting = (await http.get("/garmin/status", headers=_auth())).json()["awaiting_mfa"]

    assert response.status_code == 409
    assert awaiting is False
    # Expiry deletes the record rather than leaving the password to rot in the table.
    assert await _credential(pg_session, GARMIN_PENDING_LOGIN) is None


async def test_a_code_with_no_login_behind_it_is_a_409(
    client: ClientFactory, user: AppUser
) -> None:
    async with client() as http:
        response = await http.post("/garmin/connect/mfa", json={"code": "123456"}, headers=_auth())

    assert response.status_code == 409


async def test_rate_limiting_from_garmin_is_surfaced_not_swallowed(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    stub_begin(monkeypatch, RateLimited("Garmin rate-limited the login; wait before retrying"))

    async with client() as http:
        response = await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )

    assert response.status_code == 401
    assert "rate-limited" in response.json()["detail"]


async def test_a_short_password_is_refused_before_it_reaches_garmin(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    """A blank field should not cost an SSO request."""
    calls = stub_begin(monkeypatch, FakeClient())

    async with client() as http:
        response = await http.post(
            "/garmin/connect", json={"email": GARMIN_EMAIL, "password": ""}, headers=_auth()
        )

    assert response.status_code == 422
    assert calls == []


# ── disconnect ──────────────────────────────────────────────────────────────────


async def test_disconnect_forgets_the_credentials_but_not_the_data(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    stub_begin(monkeypatch, FakeClient())

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        response = await http.post("/garmin/disconnect", headers=_auth())

    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert await _credential(pg_session, GARMIN_TOKENS) is None

    connection = await pg_session.scalar(
        select(SourceConnection).where(SourceConnection.user_id == USER_ID)
    )
    assert connection is not None and connection.status == "needs_reauth"


# ── the history pull that starts on connect ─────────────────────────────────────


async def test_connecting_asks_for_the_history_immediately(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """Connecting a source and then showing an empty dashboard is a strange thing
    to do to someone who just handed over their password."""
    stub_begin(monkeypatch, FakeClient())
    started: list[uuid.UUID] = []

    async def fake_pull(user_id: uuid.UUID) -> None:
        started.append(user_id)

    monkeypatch.setattr(router, "pull_history", fake_pull)

    async with client() as http:
        response = await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        status_body = (await http.get("/garmin/status", headers=_auth())).json()

    assert response.status_code == 200
    assert "history" in response.json()["detail"]
    # The cursor is written in the request; the fetching happens after it.
    connection = await pg_session.scalar(
        select(SourceConnection).where(SourceConnection.user_id == USER_ID)
    )
    assert connection is not None and connection.backfill_from is not None
    assert started == [USER_ID]
    assert status_body["history"]["running"] is True
    assert status_body["history"]["progress"] == "0%"


async def test_the_mfa_path_starts_the_history_too(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    stub_begin(monkeypatch, MFARequired(client_state=STATE))
    stub_finish(monkeypatch, FakeClient())
    started: list[uuid.UUID] = []

    async def fake_pull(user_id: uuid.UUID) -> None:
        started.append(user_id)

    monkeypatch.setattr(router, "pull_history", fake_pull)

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        await http.post("/garmin/connect/mfa", json={"code": "123456"}, headers=_auth())

    assert started == [USER_ID]


async def test_a_failed_history_pull_never_reaches_the_user(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    """By the time it runs the tokens are stored and the user has been told."""
    from vitals.ingest import backfill as bf

    async def explode(*args, **kwargs):
        raise RuntimeError("garmin fell over")

    monkeypatch.setattr(bf, "run", explode)
    await router.pull_history(USER_ID)  # must not raise


# ── a bad sync must not send anyone back through SSO ────────────────────────────


async def _degrade(session: AsyncSession, status: str, detail: str) -> None:
    connection = await session.scalar(
        select(SourceConnection).where(SourceConnection.user_id == USER_ID)
    )
    assert connection is not None
    connection.status = status
    connection.status_detail = detail
    await session.commit()


async def test_a_degraded_sync_leaves_you_connected(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """The bug this exists to stop: a rate-limited run marked the connection
    `degraded`, the screen read that as disconnected and offered the login form, and
    signing in again is a fresh SSO attempt from a datacenter IP — the single most
    likely way to get a Garmin account locked. The app was steering people into the
    one thing it exists to avoid.
    """
    stub_begin(monkeypatch, FakeClient())
    monkeypatch.setattr(router, "pull_history", _noop_pull)

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        await _degrade(pg_session, "degraded", "Garmin rate-limited the run")
        body = (await http.get("/garmin/status", headers=_auth())).json()

    assert body["connected"] is True
    assert body["needs_login"] is False
    assert body["state"] == "degraded"
    assert "rate-limited" in body["trouble"]


async def test_rejected_tokens_are_the_one_case_that_does_ask_again(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """`needs_reauth` means Garmin refused the stored tokens. Signing in again is
    genuinely the fix, so this is the one state that should ask."""
    stub_begin(monkeypatch, FakeClient())
    monkeypatch.setattr(router, "pull_history", _noop_pull)

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        await _degrade(pg_session, "needs_reauth", "tokens rejected")
        body = (await http.get("/garmin/status", headers=_auth())).json()

    assert body["needs_login"] is True
    assert body["state"] == "needs_reauth"


async def test_with_no_tokens_at_all_it_asks(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        body = (await http.get("/garmin/status", headers=_auth())).json()

    assert body["connected"] is False
    assert body["needs_login"] is True
    assert body["trouble"] is None


async def test_connecting_survives_a_page_change(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    """Nothing about the connection lives in a session or a cookie — it is a row.
    Reading it back on an unrelated request is the whole test."""
    stub_begin(monkeypatch, FakeClient())
    monkeypatch.setattr(router, "pull_history", _noop_pull)

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        # Somewhere else entirely, then back.
        await http.get("/today", headers=_auth())
        body = (await http.get("/garmin/status", headers=_auth())).json()

    assert body["connected"] is True
    assert body["needs_login"] is False


async def test_sync_now_starts_a_run_and_returns(
    client: ClientFactory, user: AppUser, monkeypatch
) -> None:
    """The cron runs every six hours; "did my fix work" deserves an answer sooner."""
    stub_begin(monkeypatch, FakeClient())
    monkeypatch.setattr(router, "pull_history", _noop_pull)
    started: list[uuid.UUID] = []

    async def fake_sync(user_id: uuid.UUID) -> None:
        started.append(user_id)

    monkeypatch.setattr(router, "run_sync_now", fake_sync)

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        response = await http.post("/garmin/sync", headers=_auth())

    assert response.status_code == 200
    assert response.json()["started"] is True
    assert started == [USER_ID]


async def test_sync_now_refuses_without_a_connection(client: ClientFactory, user: AppUser) -> None:
    async with client() as http:
        assert (await http.post("/garmin/sync", headers=_auth())).status_code == 409


async def test_sync_now_respects_the_governor_s_cooldown(
    client: ClientFactory, user: AppUser, pg_session: AsyncSession, monkeypatch
) -> None:
    """Starting a run during a backoff is how a rate limit becomes a lockout, and a
    button is not a good enough reason to override the governor."""
    stub_begin(monkeypatch, FakeClient())
    monkeypatch.setattr(router, "pull_history", _noop_pull)
    started: list[uuid.UUID] = []

    async def fake_sync(user_id: uuid.UUID) -> None:  # pragma: no cover - must not run
        started.append(user_id)

    monkeypatch.setattr(router, "run_sync_now", fake_sync)

    async with client() as http:
        await http.post(
            "/garmin/connect",
            json={"email": GARMIN_EMAIL, "password": PASSWORD},
            headers=_auth(),
        )
        connection = await pg_session.scalar(
            select(SourceConnection).where(SourceConnection.user_id == USER_ID)
        )
        assert connection is not None
        connection.cooldown_until = datetime.now(UTC) + timedelta(minutes=30)
        await pg_session.commit()

        response = await http.post("/garmin/sync", headers=_auth())

    assert response.status_code == 429
    assert started == []
