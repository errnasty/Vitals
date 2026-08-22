"""`vitals` CLI — the operational surface of the app.

Phase 0 ships `doctor` and `sync`; later phases fill in `auth`, `backfill`,
`recompute`, `score`, `brief` and `coach` against the same plumbing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer
from sqlalchemy import text

from vitals import __version__
from vitals.config import get_settings
from vitals.db.session import dispose_engine, get_sessionmaker
from vitals.logging import configure_logging

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Vitals control CLI")

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
