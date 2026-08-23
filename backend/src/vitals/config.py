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
        # Fields carrying a validation_alias (VITALS_*, SUPABASE_*) stay constructible
        # by their python name, which is what makes Settings(...) usable in tests.
        populate_by_name=True,
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
    # Legacy (HS256) Supabase projects sign with this shared secret; newer projects sign
    # asymmetrically and are verified through the JWKS endpoint instead. Both are
    # supported, and locally this same secret signs `vitals auth token` dev tokens.
    supabase_jwt_secret: str | None = Field(default=None, validation_alias="SUPABASE_JWT_SECRET")

    # ── Auth (phase 1) ──────────────────────────────────────────────────────────
    # Supabase issues every end-user token with aud=authenticated. Anything else
    # (a service-role key, a token from another project) must not authenticate a user.
    jwt_audience: str = "authenticated"
    # Clock skew tolerance between Supabase and this container.
    jwt_leeway_s: int = 30
    jwks_ttl_s: int = 600
    # Floor between JWKS refetches, so an unknown `kid` cannot be used to hammer
    # Supabase's auth endpoint.
    jwks_min_refresh_s: int = 60
    jwks_timeout_s: float = 5.0

    # The single most important deployment setting: a public URL with sign-ups enabled
    # means anyone can create an account on your health app. Supabase sign-ups are
    # disabled, and this is the second, independently-enforced gate.
    allowed_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list, validation_alias="VITALS_ALLOWED_EMAILS"
    )
    # Local-only escape hatch for running the API with no auth at all. Ignored (and
    # refused at startup) anywhere but `local`.
    auth_disabled: bool = Field(default=False, validation_alias="VITALS_AUTH_DISABLED")

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

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_emails(cls, v: object) -> object:
        if isinstance(v, str):
            return [e.strip().lower() for e in v.split(",") if e.strip()]
        if isinstance(v, list):
            return [str(e).strip().lower() for e in v if str(e).strip()]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def jwt_issuer(self) -> str:
        """The `iss` every accepted token must carry.

        Supabase stamps `{SUPABASE_URL}/auth/v1`. With no project configured we fall
        back to a local sentinel that dev tokens are minted with, so the issuer check
        is always enforced rather than being skipped in development.
        """
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1"
        return "https://vitals.local/auth/v1"

    @property
    def jwks_url(self) -> str | None:
        """Asymmetric (ES256/RS256) verification endpoint; None on legacy projects."""
        if not self.supabase_url:
            return None
        return f"{self.jwt_issuer}/.well-known/jwks.json"

    @property
    def auth_configured(self) -> bool:
        """True when at least one way to verify a token exists."""
        return bool(self.supabase_jwt_secret or self.jwks_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
