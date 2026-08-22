"""Application settings.

Every service (api, web-facing or the `sync` cron) reads the same settings object, so
the sync job stays location-independent: give it DATABASE_URL + VITALS_ENCRYPTION_KEY
and it runs identically on Railway, a Pi or a laptop.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "staging", "production"]

# asyncpg does not understand libpq's `sslmode`; it wants an `ssl` argument instead.
# Supabase hands out URLs with `?sslmode=require`, so translate rather than explode.
_SSLMODE_TO_SSL = {
    "disable": None,
    "allow": None,
    "prefer": None,
    "require": "true",
    "verify-ca": "true",
    "verify-full": "true",
}


def normalize_database_url(url: str) -> str:
    """Coerce a libpq-style Postgres URL into one asyncpg + SQLAlchemy accept."""
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    if sslmode is not None:
        ssl_value = _SSLMODE_TO_SSL.get(sslmode.lower())
        if ssl_value is not None:
            query.setdefault("ssl", ssl_value)
    # pgbouncer=true is a Supabase/Prisma convention asyncpg rejects outright.
    query.pop("pgbouncer", None)

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "local"
    log_level: str = "INFO"

    # Supabase session pooler (:5432) — never the transaction pooler (:6543), which
    # breaks asyncpg's prepared statements.
    database_url: str = Field(
        default="postgresql+asyncpg://vitals:vitals@localhost:5432/vitals",
        validation_alias="DATABASE_URL",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # Encrypts Garmin credentials/tokens at rest in Supabase. Lives only in Railway env,
    # so a database compromise alone does not surrender the Garmin account.
    encryption_key: str | None = Field(default=None, validation_alias="VITALS_ENCRYPTION_KEY")

    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_anon_key: str | None = Field(default=None, validation_alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str | None = Field(
        default=None, validation_alias="SUPABASE_SERVICE_ROLE_KEY"
    )
    supabase_jwt_secret: str | None = Field(default=None, validation_alias="SUPABASE_JWT_SECRET")

    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # NoDecode: keep pydantic-settings from JSON-parsing this before the validator
    # below turns a plain comma-separated env var into a list.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # Railway injects these; used purely for traceability in /healthz.
    git_sha: str | None = Field(default=None, validation_alias="RAILWAY_GIT_COMMIT_SHA")
    railway_service: str | None = Field(default=None, validation_alias="RAILWAY_SERVICE_NAME")

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
