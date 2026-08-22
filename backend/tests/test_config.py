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
        # Supabase hands out sslmode=require; asyncpg only understands ssl=.
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
