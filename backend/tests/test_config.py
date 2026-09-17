from __future__ import annotations

import pytest

from vitals.config import normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://u:p@db.example.com:5432/postgres",
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres",
        ),
        (
            "postgres://u:p@db.example.com:5432/postgres",
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres",
        ),
        # Railway's public proxy URL carries sslmode=require; asyncpg only knows ssl=.
        (
            "postgresql://u:p@db.example.com:5432/postgres?sslmode=require",
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres?ssl=true",
        ),
        # pgbouncer=true is a Prisma-ism asyncpg rejects outright.
        (
            "postgresql://u:p@db.example.com:5432/postgres?pgbouncer=true",
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres",
        ),
        # Already-normalized URLs pass through untouched.
        (
            "postgresql+asyncpg://u:p@localhost:5432/vitals",
            "postgresql+asyncpg://u:p@localhost:5432/vitals",
        ),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_settings_normalizes_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from vitals.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/d?sslmode=require")
    assert Settings().database_url == "postgresql+asyncpg://u:p@h:5432/d?ssl=true"


def test_cors_origins_accepts_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    from vitals.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]


def test_railway_private_url_is_not_flagged_as_public() -> None:
    """The private network is the right route from inside a deploy, and free."""
    from vitals.config import Settings

    settings = Settings(
        database_url="postgresql://postgres:pw@postgres.railway.internal:5432/railway"
    )
    assert settings.database_over_public_proxy is False


@pytest.mark.parametrize(
    "host",
    ["monorail.proxy.rlwy.net", "containers-us-west-1.railway.app"],
)
def test_public_proxy_hosts_are_recognised(host: str) -> None:
    """Flagged so `doctor` can point out billed egress for a database one hop away."""
    from vitals.config import Settings

    assert Settings(
        database_url=f"postgresql://postgres:pw@{host}:23456/railway"
    ).database_over_public_proxy


def test_pooling_is_the_default_and_keeps_connections_warm() -> None:
    from vitals.config import Settings

    assert Settings().keeps_connections_warm is True


def test_pool_mode_none_lets_a_railway_service_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """A warm pool is outbound traffic, and outbound traffic is what blocks sleeping."""
    from sqlalchemy.pool import NullPool

    from vitals.config import Settings
    from vitals.db.session import get_engine

    monkeypatch.setenv("VITALS_DB_POOL_MODE", "none")
    assert Settings().keeps_connections_warm is False

    get_engine.cache_clear()
    try:
        assert isinstance(get_engine().pool, NullPool)
    finally:
        get_engine.cache_clear()


def test_a_secret_alone_makes_the_deployment_self_issuing() -> None:
    from vitals.config import SELF_ISSUER, Settings

    settings = Settings(auth_jwt_secret="x" * 40)

    assert settings.self_issued is True
    assert settings.jwt_issuer == SELF_ISSUER
    assert settings.jwks_url is None
    assert settings.auth_configured is True


def test_an_external_jwks_url_is_not_self_issuing() -> None:
    from vitals.config import Settings

    settings = Settings(
        auth_issuer="https://idp.example.com/auth/v1",
        auth_jwks_url="https://idp.example.com/auth/v1/.well-known/jwks.json",
    )

    assert settings.self_issued is False
    assert settings.auth_configured is True


def test_legacy_supabase_secret_is_still_honoured_and_named() -> None:
    from vitals.config import Settings

    settings = Settings(supabase_jwt_secret="x" * 40)

    assert settings.jwt_secret == "x" * 40
    assert settings.self_issued is True
    assert settings.legacy_supabase_env == ["SUPABASE_JWT_SECRET"]
