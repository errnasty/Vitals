"""Application settings.

Every service (api, web-facing or the `sync` cron) reads the same settings object, so
the sync job stays location-independent: give it DATABASE_URL + VITALS_ENCRYPTION_KEY
and it runs identically on Railway, a Pi or a laptop.

Nothing here is tied to a particular hosting provider. The database is whatever
`DATABASE_URL` points at, and tokens are verified against whatever key material
`VITALS_AUTH_*` describes — a self-issued secret, or an external provider's JWKS.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "staging", "production"]

# The `iss` this deployment stamps on — and requires from — its own tokens when no
# external identity provider is configured. It only has to be stable and distinct;
# nothing ever resolves it.
SELF_ISSUER = "https://vitals.self/auth/v1"

# asyncpg does not understand libpq's `sslmode`; it wants an `ssl` argument instead.
# Railway's public proxy URL arrives with `?sslmode=require`, so translate rather than
# explode.
_SSLMODE_TO_SSL = {
    "disable": None,
    "allow": None,
    "prefer": None,
    "require": "true",
    "verify-ca": "true",
    "verify-full": "true",
}

# Hosts that mean "this connection leaves Railway's network and comes back in".
# Correct from a laptop, wasteful (billed egress, extra latency) from inside Railway.
PUBLIC_PROXY_HOSTS = (".proxy.rlwy.net", ".railway.app")
# Railway's private network: free, not reachable from outside the project, IPv6-only.
PRIVATE_NETWORK_HOST = ".railway.internal"


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
    # pgbouncer=true is a Prisma convention asyncpg rejects outright.
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

    # On Railway: the Postgres service's private URL (`postgres.railway.internal`) for
    # anything running inside the project, and its public proxy URL for a laptop. Both
    # are the same database; only the path differs.
    database_url: str = Field(
        default="postgresql+asyncpg://vitals:vitals@localhost:5432/vitals",
        validation_alias="DATABASE_URL",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False
    # "none" closes every connection as soon as the request that opened it finishes.
    #
    # That is what lets a Railway service actually sleep: Railway decides a container
    # is idle from its *outbound* packets, and a warm connection pool keeps talking to
    # Postgres forever — so a pooled API never sleeps, and bills around the clock. At
    # one user the reconnect costs a few milliseconds a request and saves most of the
    # month's compute.
    db_pool_mode: Literal["pooled", "none"] = Field(
        default="pooled", validation_alias="VITALS_DB_POOL_MODE"
    )

    # Encrypts Garmin credentials/tokens at rest. Lives only in the deployment's
    # environment, so a database compromise alone does not surrender the Garmin account.
    encryption_key: str | None = Field(default=None, validation_alias="VITALS_ENCRYPTION_KEY")

    # ── Auth ────────────────────────────────────────────────────────────────────
    # Two supported shapes, both verified by the same code path:
    #
    #   self-issued  VITALS_AUTH_JWT_SECRET alone. This deployment signs its own
    #                tokens (`vitals auth token`) and verifies them with HS256. One
    #                secret, no external dependency, no service that can pause or
    #                rate-limit you. The single-user default.
    #   external     VITALS_AUTH_ISSUER + VITALS_AUTH_JWKS_URL. Any OIDC provider —
    #                Supabase, Auth0, Clerk — issues the token; this API only verifies
    #                the signature and claims locally.
    auth_issuer: str | None = Field(default=None, validation_alias="VITALS_AUTH_ISSUER")
    auth_jwks_url: str | None = Field(default=None, validation_alias="VITALS_AUTH_JWKS_URL")
    auth_jwt_secret: str | None = Field(default=None, validation_alias="VITALS_AUTH_JWT_SECRET")

    # Legacy: a Supabase project configured the two settings above implicitly. Still
    # honoured so an existing .env keeps working; `vitals doctor` points at the rename.
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_jwt_secret: str | None = Field(default=None, validation_alias="SUPABASE_JWT_SECRET")

    # Every token must carry this `aud`. Anything else (a machine key, a token from
    # another project) must not authenticate a user.
    jwt_audience: str = Field(default="authenticated", validation_alias="VITALS_AUTH_AUDIENCE")
    # Clock skew tolerance between the issuer and this container.
    jwt_leeway_s: int = 30
    jwks_ttl_s: int = 600
    # Floor between JWKS refetches, so an unknown `kid` cannot be used to hammer the
    # provider's endpoint.
    jwks_min_refresh_s: int = 60
    jwks_timeout_s: float = 5.0

    # The single most important deployment setting: a public URL with open sign-ups
    # means anyone can create an account on your health app. Enforced on every request,
    # independently of whatever the token issuer allows.
    allowed_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list, validation_alias="VITALS_ALLOWED_EMAILS"
    )
    # Local-only escape hatch for running the API with no auth at all. Ignored (and
    # refused at startup) anywhere but `local`.
    auth_disabled: bool = Field(default=False, validation_alias="VITALS_AUTH_DISABLED")

    # ── Database capabilities ───────────────────────────────────────────────────
    # pgvector backs the similar-day search in phase 9 and nothing before it. Railway's
    # official Postgres image does not ship the extension, so until phase 9 its absence
    # is reported rather than fatal. Flip this on once something depends on it.
    require_pgvector: bool = Field(default=False, validation_alias="VITALS_REQUIRE_PGVECTOR")

    # How far back a history pull reaches when a source connects. Years rather than
    # a date because the answer is "as much as there is", and Garmin's range
    # endpoints return nothing for dates before the account existed — so overshooting
    # costs a few empty responses rather than an error.
    backfill_years: int = Field(default=5, validation_alias="VITALS_BACKFILL_YEARS")

    # ── AI ──────────────────────────────────────────────────────────────────────
    # Everything above this line works with none of it set. The daily brief composes
    # itself in Python when there is no key, so an unconfigured deployment loses the
    # prose and keeps the facts.
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # An OpenRouter model slug (`vendor/model`, as its catalogue lists it). Swappable
    # on purpose: the brief is sixty words written from numbers Python already
    # computed, so this is the cheapest dial in the app to turn.
    ai_model: str = Field(default="anthropic/claude-sonnet-5", validation_alias="VITALS_AI_MODEL")
    # Sixty words needs nowhere near this; the cap is a runaway guard, not a target.
    ai_max_output_tokens: int = Field(default=300, validation_alias="VITALS_AI_MAX_TOKENS")
    ai_timeout_s: float = Field(default=30.0, validation_alias="VITALS_AI_TIMEOUT_S")
    # A brief is only rewritten when the day's digest changes, so a re-run is free.
    # Set this to force one — after editing the prompt, say.
    ai_force_regenerate: bool = Field(default=False, validation_alias="VITALS_AI_FORCE")

    # NoDecode: keep pydantic-settings from JSON-parsing this before the validator
    # below turns a plain comma-separated env var into a list.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # Railway injects these; used purely for traceability in /healthz and by `doctor`
    # to tell "running inside Railway" from "running on your laptop".
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
    def in_railway(self) -> bool:
        return self.railway_service is not None

    @property
    def database_host(self) -> str:
        return urlsplit(self.database_url).hostname or ""

    @property
    def database_over_public_proxy(self) -> bool:
        """True when the DSN takes the long way round to a Railway database.

        Correct from a laptop. From inside Railway it is billed egress and extra
        latency for a database sitting on the other side of the private network.
        """
        host = self.database_host
        return any(host.endswith(suffix) for suffix in PUBLIC_PROXY_HOSTS)

    @property
    def keeps_connections_warm(self) -> bool:
        """True when this process holds Postgres connections open between requests."""
        return self.db_pool_mode == "pooled"

    @property
    def jwt_secret(self) -> str | None:
        """The HS256 key, whatever it was configured under."""
        return self.auth_jwt_secret or self.supabase_jwt_secret

    @property
    def jwt_issuer(self) -> str:
        """The `iss` every accepted token must carry.

        An external provider sets it explicitly (a legacy Supabase project derived it
        from the project URL). With none configured we fall back to the self-issued
        sentinel that `vitals auth token` mints against, so the issuer check is always
        enforced rather than silently skipped.
        """
        if self.auth_issuer:
            return self.auth_issuer.rstrip("/")
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1"
        return SELF_ISSUER

    @property
    def jwks_url(self) -> str | None:
        """Asymmetric (ES256/RS256) verification endpoint; None when self-issuing."""
        if self.auth_jwks_url:
            return self.auth_jwks_url
        if self.supabase_url:
            return f"{self.jwt_issuer}/.well-known/jwks.json"
        return None

    @property
    def auth_configured(self) -> bool:
        """True when at least one way to verify a token exists."""
        return bool(self.jwt_secret or self.jwks_url)

    @property
    def self_issued(self) -> bool:
        """True when this deployment is its own identity provider.

        That is what makes `vitals auth token` legitimate outside local development:
        there is no external issuer whose tokens it would be forging.
        """
        return self.jwks_url is None and self.jwt_issuer == SELF_ISSUER and bool(self.jwt_secret)

    @property
    def ai_configured(self) -> bool:
        """True when a model can actually be called. False is a supported state."""
        return bool(self.openrouter_api_key)

    @property
    def legacy_supabase_env(self) -> list[str]:
        """Supabase-named variables still doing the work of a VITALS_AUTH_* one."""
        names = []
        if self.supabase_jwt_secret and not self.auth_jwt_secret:
            names.append("SUPABASE_JWT_SECRET")
        if self.supabase_url and not (self.auth_issuer and self.auth_jwks_url):
            names.append("SUPABASE_URL")
        return names


@lru_cache
def get_settings() -> Settings:
    return Settings()
