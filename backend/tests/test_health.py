"""Health endpoint tests — no database required.

The DB session is overridden so CI can assert the routing/serialisation contract
without a Postgres service; the real connectivity check is `vitals doctor`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from vitals.api.main import create_app
from vitals.db.session import get_session


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    def __init__(self, *, fail: bool = False, vector: str | None = "0.8.0") -> None:
        self.fail = fail
        self.vector = vector

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if self.fail:
            raise ConnectionRefusedError("no database")
        sql = str(statement)
        if "pg_extension" in sql:
            return _FakeResult(self.vector)
        return _FakeResult(1)


def _client(session: _FakeSession) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_livez_does_not_touch_the_database() -> None:
    async with _client(_FakeSession(fail=True)) as client:
        response = await client.get("/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_healthz_reports_database_and_pgvector() -> None:
    async with _client(_FakeSession()) as client:
        response = await client.get("/healthz")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["pgvector"] == {
        "ok": True,
        "present": True,
        "version": "0.8.0",
        "required": False,
    }


async def test_healthz_reports_missing_pgvector_without_failing() -> None:
    """Railway's official Postgres image has no pgvector, and nothing needs it yet."""
    async with _client(_FakeSession(vector=None)) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["checks"]["pgvector"] == {
        "ok": True,
        "present": False,
        "version": None,
        "required": False,
    }


async def test_healthz_fails_on_missing_pgvector_once_it_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 9 flips the switch, and the same absence becomes a real outage."""
    monkeypatch.setenv("VITALS_REQUIRE_PGVECTOR", "true")

    async with _client(_FakeSession(vector=None)) as client:
        response = await client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["checks"]["pgvector"]["ok"] is False


@pytest.mark.parametrize("path", ["/healthz"])
async def test_healthz_returns_503_when_database_is_down(path: str) -> None:
    async with _client(_FakeSession(fail=True)) as client:
        response = await client.get(path)
    assert response.status_code == 503
    assert response.json()["checks"]["database"]["ok"] is False
