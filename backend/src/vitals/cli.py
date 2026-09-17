"""`vitals` CLI — the operational surface of the app.

Phase 0 ships `doctor` and `sync`; later phases fill in `auth`, `backfill`,
`recompute`, `score`, `brief` and `coach` against the same plumbing.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import typer
from cryptography.fernet import Fernet
from sqlalchemy import text

from vitals import __version__
from vitals.config import get_settings
from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.logging import configure_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Vitals control CLI")
auth_app = typer.Typer(no_args_is_help=True, help="Authentication helpers (local development)")
app.add_typer(auth_app, name="auth")
garmin_app = typer.Typer(no_args_is_help=True, help="Garmin connection management")
app.add_typer(garmin_app, name="garmin")

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
    if settings.in_railway and settings.database_over_public_proxy:
        # Same database either way, but the public proxy leaves Railway's network and
        # comes back in: billed egress and extra latency for nothing.
        line(
            WARN,
            "database route",
            "public proxy from inside Railway; reference the private DATABASE_URL instead",
        )
    if ":6543" in settings.database_url:
        line(
            WARN,
            "pooler port",
            "6543 is usually a transaction pooler; asyncpg needs prepared statements",
        )
    if settings.in_railway and settings.keeps_connections_warm:
        # Railway judges idleness by outbound packets, and a warm pool never stops
        # producing them — so a pooled service bills around the clock even unused.
        line(
            WARN,
            "connection pool",
            "warm pool keeps this service awake; set VITALS_DB_POOL_MODE=none to let it sleep",
        )
    if not settings.encryption_key:
        line(WARN, "VITALS_ENCRYPTION_KEY", "unset - Garmin credentials cannot be stored")
    else:
        try:
            Fernet(settings.encryption_key.encode())
            line(OK, "VITALS_ENCRYPTION_KEY", "set, valid Fernet key")
        except (ValueError, TypeError):
            # A key that does not parse means every stored credential is unreadable,
            # which surfaces as a mysterious re-auth loop if it is not caught here.
            line(BAD, "VITALS_ENCRYPTION_KEY", "set but not a valid Fernet key")
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
                OK if vector else (BAD if settings.require_pgvector else WARN),
                "pgvector",
                f"v{vector}" if vector else "not available on this image (needed from phase 9)",
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

            typer.echo("")
            typer.echo("garmin")
            await _doctor_garmin(session, line)
    except Exception as exc:  # noqa: BLE001 - doctor reports, never raises
        line(BAD, "connection", f"{type(exc).__name__}: {exc}")

    await dispose_engine()
    typer.echo("")
    typer.echo("FAILED" if failures else "OK")
    return 1 if failures else 0


async def _doctor_garmin(session: Any, line: Callable[..., None]) -> None:
    """Connection health, without making a single request to Garmin."""
    from vitals.ingest.pipeline import NoSuchUser, connection_for, resolve_user
    from vitals.ingest.raw_store import RawStore

    try:
        user = await resolve_user(session)
    except NoSuchUser as exc:
        line(WARN, "account", str(exc)[:80])
        return

    connection = await connection_for(session, user.id)
    if connection is None:
        line(WARN, "connection", "not connected - run `vitals garmin login` locally")
    else:
        status = {"active": OK, "degraded": WARN, "needs_reauth": BAD, "disabled": WARN}
        detail = connection.status
        if connection.status_detail:
            detail += f" ({connection.status_detail[:60]})"
        line(status.get(connection.status, WARN), "connection", detail)
        if connection.cooldown_until:
            line(WARN, "cooldown", f"rate-limited until {connection.cooldown_until.isoformat()}")
        if connection.last_success_at:
            line(OK, "last sync", connection.last_success_at.isoformat())

    store = RawStore(session, user_id=user.id, source="garmin")
    total = await store.count()
    first, last = await store.date_range()
    line(
        OK if total else WARN,
        "bronze",
        f"{total} payload(s)" + (f", {first} to {last}" if first and last else ""),
    )


async def _doctor_auth(settings: Any, line: Callable[..., None]) -> None:
    """Report every way this deployment could be serving health data unprotected."""
    methods = []
    if settings.jwks_url:
        methods.append("JWKS (asymmetric)")
    if settings.jwt_secret:
        methods.append("shared secret (HS256)")
    line(
        OK if methods else (WARN if settings.is_local else BAD),
        "verification",
        " + ".join(methods) if methods else "none configured - every request will 401",
    )
    line(OK, "issuer", settings.jwt_issuer)
    line(
        OK,
        "mode",
        "self-issued (`vitals auth token` mints them)"
        if settings.self_issued
        else "external issuer",
    )
    secret = settings.jwt_secret
    if secret and len(secret.encode()) < 32:
        # RFC 7518 §3.2: an HS256 key shorter than the hash output weakens the
        # signature. Anything under 32 bytes is almost always a hand-typed value.
        line(WARN, "secret length", "the HS256 secret is under 32 bytes")
    if settings.legacy_supabase_env:
        line(
            WARN,
            "legacy env",
            f"{', '.join(settings.legacy_supabase_env)} still in use; "
            "rename to VITALS_AUTH_JWT_SECRET / VITALS_AUTH_ISSUER + VITALS_AUTH_JWKS_URL",
        )

    if settings.allowed_emails:
        line(OK, "allowlist", f"{len(settings.allowed_emails)} address(es)")
    else:
        line(
            WARN if settings.is_local else BAD,
            "allowlist",
            "VITALS_ALLOWED_EMAILS is empty - any account the issuer accepts would be let in",
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
    days: int | None = typer.Option(
        None, "--days", "-d", help="Lifetime in days; overrides --hours"
    ),
    user_id: str | None = typer.Option(None, "--user-id", help="Override the derived user id"),
) -> None:
    """Mint an access token this deployment signs itself.

    Legitimate wherever no external issuer is configured: there is nobody else's `iss`
    to forge. Refused when one is, because then the token has to come from them.
    """
    from vitals.auth.tokens import MintRefused, mint_token

    settings = get_settings()
    ttl = timedelta(days=days) if days is not None else timedelta(hours=hours)
    try:
        token = mint_token(
            settings,
            email=email,
            user_id=uuid.UUID(user_id) if user_id else None,
            ttl=ttl,
        )
    except (MintRefused, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

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
def sync(
    source: str = typer.Option("garmin", help="Source to sync"),
    days: int = typer.Option(7, "--days", help="Trailing window; catches Garmin's revisions"),
    email: str | None = typer.Option(None, "--email", help="Account to sync, if several exist"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request plan, fetch nothing"),
) -> None:
    """Run an incremental sync. Invoked by the Railway `sync` cron service."""
    configure_logging()
    if source != "garmin":
        typer.secho(f"unknown source {source!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if dry_run:
        from vitals.sources.garmin.plan import describe_plan, plan_incremental

        typer.echo(describe_plan(plan_incremental(today=date.today(), days=days)))
        typer.echo("(activity detail adds up to 3 requests per unseen activity)")
        return

    from vitals.workers.jobs import run_sync, shutdown

    async def _run() -> Any:
        try:
            return await run_sync(source=source, days=days, email=email)
        finally:
            await shutdown()

    raise typer.Exit(_report(asyncio.run(_run())))


@app.command()
def backfill(
    start: str = typer.Option(..., "--start", help="First day to fetch, YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="Last day (default: today)"),
    email: str | None = typer.Option(None, "--email", help="Account to backfill"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request plan, fetch nothing"),
) -> None:
    """Pull years of history in one go. Manual by design — never put this on a cron.

    Uses only the range endpoints, which cover a year in one or two requests where a
    per-day loop would take 365.
    """
    configure_logging()
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end) if end else date.today()
    except ValueError as exc:
        typer.secho(f"bad date: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if first > last:
        typer.secho("--start is after --end", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if dry_run:
        from vitals.sources.garmin.plan import describe_plan, plan_backfill

        typer.echo(describe_plan(plan_backfill(start=first, end=last)))
        return

    from vitals.workers.jobs import run_history, shutdown

    async def _run() -> Any:
        try:
            return await run_history(start=first, end=last, email=email)
        finally:
            await shutdown()

    typer.echo(f"backfilling {first} to {last} ({(last - first).days + 1} days)")
    raise typer.Exit(_report(asyncio.run(_run())))


@app.command()
def normalize(
    since: str | None = typer.Option(None, "--since", help="First day to rebuild, YYYY-MM-DD"),
    until: str | None = typer.Option(None, "--until", help="Last day (default: no limit)"),
    endpoints: str | None = typer.Option(
        None, "--endpoints", help="Only these bronze endpoints, comma-separated"
    ),
    email: str | None = typer.Option(None, "--email", help="Account to rebuild, if several exist"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be produced, write nothing"
    ),
) -> None:
    """Rebuild the silver layer from bronze.

    Safe to run as often as you like: every write is an upsert keyed on the natural
    key, so this is a projection of bronze rather than an accumulation. After fixing a
    normalizer, run it again over the affected window and the numbers change in place.
    """
    configure_logging()
    try:
        start = date.fromisoformat(since) if since else None
        end = date.fromisoformat(until) if until else None
    except ValueError as exc:
        typer.secho(f"bad date: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    selected = [e.strip() for e in endpoints.split(",") if e.strip()] if endpoints else None

    async def _run() -> int:
        from vitals.ingest.pipeline import NoSuchUser, resolve_user
        from vitals.normalize import available_metrics
        from vitals.normalize import normalize as run_normalize

        async with get_sessionmaker()() as session:
            try:
                user = await resolve_user(session, email=email)
            except NoSuchUser as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                return 1

            result = await run_normalize(
                session,
                user_id=user.id,
                start=start,
                end=end,
                endpoints=selected,
                dry_run=dry_run,
            )

            if dry_run:
                typer.secho("dry run - nothing written", fg=typer.colors.YELLOW)
            typer.echo(f"{result.payloads} payload(s) read, {result.rows} silver row(s)")
            typer.echo(
                f"  daily {result.daily}  samples {result.samples}  "
                f"sleep {result.sleep}  activities {result.activities}"
            )

            if result.coverage:
                typer.echo("")
                typer.echo("coverage")
                for item in sorted(result.coverage, key=lambda c: c.endpoint):
                    # Barren payloads are the signal that matters: a normalizer written
                    # against the library's documented shape meeting a different one.
                    status = OK if item.ok else WARN
                    detail = f"{item.payloads} payload(s) -> {item.rows} row(s)"
                    if item.barren:
                        detail += f", {item.barren} produced nothing"
                    typer.echo(f"  [{status}] {item.endpoint}: {detail}")

            if result.unmapped:
                typer.echo("")
                typer.secho(
                    f"no normalizer for: {', '.join(result.unmapped)}", fg=typer.colors.YELLOW
                )
            if result.rejected:
                typer.secho(f"{result.rejected} value(s) rejected", fg=typer.colors.RED)

            if not dry_run:
                inventory = await available_metrics(session, user_id=user.id)
                typer.echo("")
                typer.echo(f"metrics ({len(inventory)})")
                for metric, (first, last, days) in inventory.items():
                    typer.echo(f"  {metric:<32} {days:>5} day(s)  {first} to {last}")
        return 0

    async def _wrapped() -> int:
        try:
            return await _run()
        finally:
            await dispose_engine()

    raise typer.Exit(asyncio.run(_wrapped()))


def _report(outcome: Any) -> int:
    """Print a sync outcome and turn it into an exit code."""
    colour = {
        "success": typer.colors.GREEN,
        "partial": typer.colors.YELLOW,
        "degraded": typer.colors.YELLOW,
        "failed": typer.colors.RED,
    }.get(outcome.status, typer.colors.WHITE)
    typer.secho(f"{outcome.status}", fg=colour)
    typer.echo(
        f"  {outcome.requests} request(s), {outcome.stored} new payload(s), "
        f"{outcome.unchanged} unchanged"
    )
    if outcome.detail:
        typer.echo(f"  {outcome.detail}")
    return 0 if outcome.ok else 1


@garmin_app.command("login")
def garmin_login(
    email: str = typer.Option(..., "--email", "-e", help="Garmin Connect address"),
    user_email: str | None = typer.Option(
        None, "--user-email", help="Vitals account to attach to (defaults to the only one)"
    ),
    store_password: bool = typer.Option(
        False,
        "--store-password",
        help="Also store the password, enabling unattended re-login (see the warning)",
    ),
) -> None:
    """Log in to Garmin and store the tokens, encrypted, in the database.

    Run this on your own machine. Garmin's SSO sits behind Cloudflare, which treats
    datacenter IPs far more harshly than residential ones, and this is the only command
    that touches the SSO path at all — everything afterwards refreshes tokens over the
    ordinary API. The OAuth token is good for about a year, so this is a once-a-year
    manual step rather than something Railway ever does.
    """
    configure_logging()
    settings = get_settings()
    if not settings.is_local:
        typer.secho(
            f"warning: environment={settings.environment}. Garmin's SSO punishes datacenter "
            "IPs; run this from your own machine against the same DATABASE_URL.",
            fg=typer.colors.YELLOW,
            err=True,
        )

    password = typer.prompt("Garmin password", hide_input=True)

    async def _login() -> int:
        from vitals.db.models import GARMIN_PASSWORD, GARMIN_TOKENS, SourceConnection
        from vitals.ingest.pipeline import NoSuchUser, connection_for, resolve_user
        from vitals.security.vault import VaultUnavailable, build_vault
        from vitals.sources.garmin import GarminError, RateGovernor, login_with_credentials

        async with get_sessionmaker()() as session:
            try:
                user = await resolve_user(session, email=user_email)
                vault = build_vault(session, settings)
            except (NoSuchUser, VaultUnavailable) as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                return 1

            try:
                client = await login_with_credentials(
                    email,
                    password,
                    governor=RateGovernor(),
                    prompt_mfa=lambda: typer.prompt("Garmin MFA code"),
                )
            except GarminError as exc:
                typer.secho(f"login failed: {exc}", fg=typer.colors.RED, err=True)
                return 1

            await vault.put(user.id, GARMIN_TOKENS, client.export_tokens())
            if store_password:
                await vault.put(user.id, GARMIN_PASSWORD, password)

            connection = await connection_for(session, user.id)
            if connection is None:
                connection = SourceConnection(user_id=user.id, source="garmin")
                session.add(connection)
            connection.status = "active"
            connection.status_detail = None
            connection.external_id = client.display_name
            connection.consecutive_failures = 0
            connection.cooldown_until = None
            await session.commit()

        typer.secho(
            f"[{OK}] tokens stored for {client.display_name or email}", fg=typer.colors.GREEN
        )
        typer.echo("  they refresh automatically from now on; no further SSO logins needed")
        return 0

    async def _run() -> int:
        try:
            return await _login()
        finally:
            await dispose_engine()

    raise typer.Exit(asyncio.run(_run()))


@garmin_app.command("status")
def garmin_status(
    user_email: str | None = typer.Option(None, "--user-email", help="Account to inspect"),
) -> None:
    """Connection state, token age and how much history has landed in bronze."""
    configure_logging()

    async def _status() -> int:
        from vitals.db.models import GARMIN_TOKENS
        from vitals.ingest.pipeline import NoSuchUser, connection_for, resolve_user
        from vitals.ingest.raw_store import RawStore
        from vitals.security.vault import VaultUnavailable, build_vault

        async with get_sessionmaker()() as session:
            try:
                user = await resolve_user(session, email=user_email)
            except NoSuchUser as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                return 1

            typer.echo(f"account   {user.email} ({user.id})")
            connection = await connection_for(session, user.id)
            if connection is None:
                typer.secho(f"[{WARN}] no Garmin connection; run `vitals garmin login`")
                return 1

            state = OK if connection.status == "active" else WARN
            typer.echo(f"status    [{state}] {connection.status}")
            if connection.status_detail:
                typer.echo(f"          {connection.status_detail}")
            typer.echo(f"garmin    {connection.external_id or '-'}")
            typer.echo(f"last ok   {connection.last_success_at or 'never'}")
            typer.echo(f"failures  {connection.consecutive_failures}")
            if connection.cooldown_until:
                typer.echo(f"cooldown  until {connection.cooldown_until.isoformat()}")

            try:
                tokens = await build_vault(session, get_settings()).get(user.id, GARMIN_TOKENS)
                typer.echo(f"tokens    {'stored' if tokens else 'MISSING'}")
            except VaultUnavailable as exc:
                typer.secho(f"tokens    [{BAD}] {exc}", fg=typer.colors.RED)

            store = RawStore(session, user_id=user.id, source="garmin")
            first, last = await store.date_range()
            typer.echo(f"bronze    {await store.count()} payload(s)")
            if first and last:
                typer.echo(f"          {first} to {last}")
        return 0

    async def _run() -> int:
        try:
            return await _status()
        finally:
            await dispose_engine()

    raise typer.Exit(asyncio.run(_run()))


@garmin_app.command("test")
def garmin_test(
    user_email: str | None = typer.Option(None, "--user-email", help="Account to test"),
) -> None:
    """Make one authenticated call from this host.

    The point is the host, not the call: this is how you find out whether Garmin's
    Cloudflare layer tolerates Railway's datacenter IP before a real sync depends on it.
    """
    configure_logging()

    async def _test() -> int:
        from vitals.db.models import GARMIN_TOKENS
        from vitals.ingest.pipeline import NoSuchUser, resolve_user
        from vitals.security.vault import VaultUnavailable, build_vault
        from vitals.sources.garmin import GarminClient, GarminError, RateGovernor

        async with get_sessionmaker()() as session:
            try:
                user = await resolve_user(session, email=user_email)
                tokens = await build_vault(session, get_settings()).get(user.id, GARMIN_TOKENS)
            except (NoSuchUser, VaultUnavailable) as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                return 1
            if not tokens:
                typer.secho(
                    f"[{BAD}] no stored tokens; run `vitals garmin login`", fg=typer.colors.RED
                )
                return 1

            try:
                client = await GarminClient.from_tokens(tokens, governor=RateGovernor())
                profile = await client.call("get_user_profile")
            except GarminError as exc:
                typer.secho(f"[{BAD}] {type(exc).__name__}: {exc}", fg=typer.colors.RED)
                return 1

            # The refresh this call may have performed is only in memory until stored.
            vault = build_vault(session, get_settings())
            if await vault.put(user.id, GARMIN_TOKENS, client.export_tokens()):
                typer.echo("  tokens were refreshed and re-stored")

            name = (profile or {}).get("userName") or client.display_name or "(unknown)"
            typer.secho(f"[{OK}] authenticated as {name}", fg=typer.colors.GREEN)
        return 0

    async def _run() -> int:
        try:
            return await _test()
        finally:
            await dispose_engine()

    raise typer.Exit(asyncio.run(_run()))


@garmin_app.command("logout")
def garmin_logout(
    user_email: str | None = typer.Option(None, "--user-email", help="Account to disconnect"),
) -> None:
    """Delete the stored Garmin tokens and password."""
    configure_logging()

    async def _logout() -> int:
        from vitals.db.models import GARMIN_PASSWORD, GARMIN_TOKENS
        from vitals.ingest.pipeline import NoSuchUser, connection_for, resolve_user
        from vitals.security.vault import VaultUnavailable, build_vault

        async with get_sessionmaker()() as session:
            try:
                user = await resolve_user(session, email=user_email)
                vault = build_vault(session, get_settings())
            except (NoSuchUser, VaultUnavailable) as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                return 1

            removed = await vault.delete(user.id, GARMIN_TOKENS)
            await vault.delete(user.id, GARMIN_PASSWORD)
            connection = await connection_for(session, user.id)
            if connection is not None:
                connection.status = "needs_reauth"
                connection.status_detail = "disconnected locally"
                await session.commit()

        typer.echo("tokens removed" if removed else "no tokens were stored")
        return 0

    async def _run() -> int:
        try:
            return await _logout()
        finally:
            await dispose_engine()

    raise typer.Exit(asyncio.run(_run()))


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
