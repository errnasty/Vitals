"""`vitals` CLI — the operational surface of the app.

Phase 0 ships `doctor` and `sync`; later phases fill in `auth`, `backfill`,
`recompute`, `score`, `brief` and `coach` against the same plumbing.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import typer
from sqlalchemy import text

from vitals import __version__
from vitals.config import get_settings
from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.logging import configure_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Vitals control CLI")
auth_app = typer.Typer(no_args_is_help=True, help="Authentication helpers (local development)")
app.add_typer(auth_app, name="auth")

OK = "PASS"
BAD = "FAIL"
WARN = "WARN"


def _redact(url: str) -> str:
    """Show enough of the DSN to debug host/port/database without leaking the password."""
    if "@" not in url:
        return url
    scheme_and_creds, _, rest = url.partition("@")
    scheme, _, _creds = scheme_and_creds.partition("://")
    return f"{scheme}://***@{rest}"


def _alembic_head() -> str | None:
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not ini.exists():
        return None
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ini)))
    return script.get_current_head()


async def _doctor() -> int:
    settings = get_settings()
    failures = 0

    def line(status: str, label: str, detail: str = "") -> None:
        nonlocal failures
        if status == BAD:
            failures += 1
        typer.echo(f"  [{status}] {label}{f': {detail}' if detail else ''}")

    typer.echo(f"vitals {__version__} (environment={settings.environment})")
    typer.echo("")
    typer.echo("config")
    line(OK, "database_url", _redact(settings.database_url))
    if ":6543" in settings.database_url:
        line(
            WARN,
            "pooler port",
            "6543 is the transaction pooler; asyncpg needs the session pooler (5432)",
        )
    line(
        OK if settings.encryption_key else WARN,
        "VITALS_ENCRYPTION_KEY",
        "set" if settings.encryption_key else "unset (required from phase 2)",
    )
    line(
        OK if settings.supabase_url else WARN,
        "SUPABASE_URL",
        "set" if settings.supabase_url else "unset (required from phase 1)",
    )
    line(
        OK if settings.openrouter_api_key else WARN,
        "OPENROUTER_API_KEY",
        "set" if settings.openrouter_api_key else "unset (required from phase 7)",
    )

    typer.echo("")
    typer.echo("auth")
    await _doctor_auth(settings, line)

    typer.echo("")
    typer.echo("database")
    try:
        async with get_sessionmaker()() as session:
            server = (await session.execute(text("show server_version"))).scalar_one()
            line(OK, "connection", f"postgres {server}")

            vector = (
                await session.execute(
                    text("select extversion from pg_extension where extname = 'vector'")
                )
            ).scalar_one_or_none()
            line(
                OK if vector else BAD,
                "pgvector",
                f"v{vector}" if vector else "extension not enabled",
            )

            current = (
                await session.execute(
                    text(
                        "select version_num from alembic_version"
                        " where to_regclass('alembic_version') is not null"
                    )
                )
            ).scalar_one_or_none()
            head = _alembic_head()
            if current is None:
                line(BAD, "migrations", "alembic_version empty - run `alembic upgrade head`")
            elif head is None:
                line(WARN, "migrations", f"at {current} (head unknown outside the repo)")
            elif current == head:
                line(OK, "migrations", f"at head {current}")
            else:
                line(BAD, "migrations", f"at {current}, head is {head}")

            runs = (await session.execute(text("select count(*) from sync_run"))).scalar_one()
            line(OK, "sync_run", f"{runs} run(s) recorded")
    except Exception as exc:  # noqa: BLE001 - doctor reports, never raises
        line(BAD, "connection", f"{type(exc).__name__}: {exc}")

    await dispose_engine()
    typer.echo("")
    typer.echo("FAILED" if failures else "OK")
    return 1 if failures else 0


async def _doctor_auth(settings: Any, line: Callable[..., None]) -> None:
    """Report every way this deployment could be serving health data unprotected."""
    methods = []
    if settings.jwks_url:
        methods.append("JWKS (asymmetric)")
    if settings.supabase_jwt_secret:
        methods.append("shared secret (HS256)")
    line(
        OK if methods else (WARN if settings.is_local else BAD),
        "verification",
        " + ".join(methods) if methods else "none configured - every request will 401",
    )
    line(OK, "issuer", settings.jwt_issuer)
    if settings.supabase_jwt_secret and len(settings.supabase_jwt_secret.encode()) < 32:
        # RFC 7518 §3.2: an HS256 key shorter than the hash output weakens the signature.
        # Supabase's own secret is longer, so this almost always means a hand-typed value.
        line(WARN, "secret length", "SUPABASE_JWT_SECRET is under 32 bytes")

    if settings.allowed_emails:
        line(OK, "allowlist", f"{len(settings.allowed_emails)} address(es)")
    else:
        line(
            WARN if settings.is_local else BAD,
            "allowlist",
            "VITALS_ALLOWED_EMAILS is empty - any Supabase account would be accepted",
        )

    if settings.auth_disabled:
        line(
            WARN if settings.is_local else BAD,
            "VITALS_AUTH_DISABLED",
            "auth is switched off" + ("" if settings.is_local else " outside local"),
        )

    if settings.jwks_url:
        # A real fetch, because "the URL looks right" is not the failure mode that
        # bites: a paused project or a wrong ref returns a perfectly plausible 404.
        try:
            async with httpx.AsyncClient(timeout=settings.jwks_timeout_s) as client:
                response = await client.get(settings.jwks_url)
                response.raise_for_status()
                keys = response.json().get("keys", [])
            algs = sorted({k.get("alg", "?") for k in keys})
            line(
                OK if keys else BAD,
                "jwks",
                f"{len(keys)} key(s) [{', '.join(algs)}]" if keys else "endpoint returned no keys",
            )
        except Exception as exc:  # noqa: BLE001 - doctor reports, never raises
            line(BAD, "jwks", f"{settings.jwks_url}: {type(exc).__name__}")


@auth_app.command("token")
def auth_token(
    email: str = typer.Option(..., "--email", "-e", help="Address to mint the token for"),
    hours: int = typer.Option(12, "--hours", "-h", help="Lifetime in hours"),
    user_id: str | None = typer.Option(None, "--user-id", help="Override the derived user id"),
) -> None:
    """Mint a local Supabase-shaped access token (local environment only)."""
    from vitals.auth.dev import mint_dev_token

    settings = get_settings()
    try:
        token = mint_dev_token(
            settings,
            email=email,
            user_id=uuid.UUID(user_id) if user_id else None,
            ttl=timedelta(hours=hours),
        )
    except (RuntimeError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if settings.allowed_emails and email.strip().lower() not in settings.allowed_emails:
        typer.secho(
            f"warning: {email} is not in VITALS_ALLOWED_EMAILS; requests will be rejected with 403",
            fg=typer.colors.YELLOW,
            err=True,
        )
    typer.echo(token)


@auth_app.command("verify")
def auth_verify(
    token: str | None = typer.Argument(None, help="Token to verify; omit to read stdin"),
) -> None:
    """Verify a token exactly as the API would, and print what it proves."""
    from vitals.api.deps import get_verifier
    from vitals.auth.errors import AuthError
    from vitals.auth.policy import check_allowed

    raw = (token or sys.stdin.read()).strip()
    if not raw:
        typer.secho("no token supplied", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    async def _verify() -> int:
        try:
            principal = await get_verifier().verify(raw)
            check_allowed(get_settings(), principal)
        except AuthError as exc:
            typer.secho(f"[{BAD}] {exc.code}: {exc.detail}", fg=typer.colors.RED)
            return 1
        typer.echo(f"[{OK}] {principal.email or '(no email)'}")
        typer.echo(f"  user_id   {principal.user_id}")
        typer.echo(f"  role      {principal.role}")
        typer.echo(f"  issued    {principal.issued_at.isoformat()}")
        typer.echo(f"  expires   {principal.expires_at.isoformat()}")
        typer.echo(f"  assurance {principal.assurance_level or '-'}")
        return 0

    configure_logging()
    raise typer.Exit(asyncio.run(_verify()))


@app.command()
def doctor() -> None:
    """Check config, database, extensions and migration state."""
    configure_logging()
    raise typer.Exit(asyncio.run(_doctor()))


@app.command()
def sync(source: str = typer.Option("garmin", help="Source to sync")) -> None:
    """Run an incremental sync. Invoked by the Railway `sync` cron service."""
    configure_logging()
    from vitals.workers.jobs import run_sync, shutdown

    async def _run() -> Any:
        try:
            return await run_sync(source=source)
        finally:
            await shutdown()

    run_id = asyncio.run(_run())
    typer.echo(f"sync_run {run_id}")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
