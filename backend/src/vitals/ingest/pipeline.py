"""Assembling a sync: resolve the user, build the source, run it.

The `sync` service and the CLI both come through here, so "how a sync is wired" lives
in one place and the Railway cron job is genuinely the same code path a developer runs
by hand.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import Settings, get_settings
from vitals.db.models import AppUser, SourceConnection
from vitals.security.vault import build_vault
from vitals.sources.base import SyncOutcome
from vitals.sources.garmin import SOURCE, GarminClient, GarminSource, RateGovernor


class NoSuchUser(RuntimeError):
    """Identity comes from the auth layer, never from a sync command."""


async def resolve_user(session: AsyncSession, *, email: str | None = None) -> AppUser:
    """Find the user a sync runs as.

    Deliberately does not create anybody: an `app_user` row is minted by an
    authenticated request, so its id is the Supabase `sub`. Inventing one here would
    produce an orphan row that the first real sign-in would silently shadow, taking the
    Garmin connection with it.
    """
    if email is not None:
        result = await session.execute(select(AppUser).where(AppUser.email == email.lower()))
        user = result.scalar_one_or_none()
        if user is None:
            raise NoSuchUser(
                f"no account for {email}. Sign in once so the account exists — locally: "
                '`curl -H "Authorization: Bearer $(vitals auth token --email '
                f'{email})" localhost:8000/auth/me`'
            )
        return user

    # Single-user deployment: prefer the account that already has a connection.
    connected = (
        (
            await session.execute(
                select(AppUser)
                .join(SourceConnection, SourceConnection.user_id == AppUser.id)
                .where(SourceConnection.source == SOURCE)
            )
        )
        .scalars()
        .all()
    )
    if len(connected) == 1:
        return connected[0]
    if len(connected) > 1:
        raise NoSuchUser("several accounts have a Garmin connection; pass --email")

    users = (await session.execute(select(AppUser).limit(2))).scalars().all()
    if not users:
        raise NoSuchUser("no accounts exist yet; sign in once before syncing")
    if len(users) > 1:
        raise NoSuchUser("several accounts exist; pass --email")
    return users[0]


def build_garmin_source(
    session: AsyncSession, *, user_id: uuid.UUID, settings: Settings | None = None
) -> GarminSource:
    settings = settings or get_settings()
    return GarminSource(
        session,
        user_id=user_id,
        vault=build_vault(session, settings),
        client_factory=_connect,
    )


async def _connect(tokens: str, governor: RateGovernor) -> GarminClient:
    return await GarminClient.from_tokens(tokens, governor=governor)


async def run_incremental(
    session: AsyncSession, *, email: str | None = None, days: int = 7
) -> SyncOutcome:
    user = await resolve_user(session, email=email)
    return await build_garmin_source(session, user_id=user.id).incremental(days=days)


async def run_backfill(
    session: AsyncSession, *, start: date, end: date, email: str | None = None
) -> SyncOutcome:
    user = await resolve_user(session, email=email)
    return await build_garmin_source(session, user_id=user.id).backfill(start=start, end=end)


async def connection_for(
    session: AsyncSession, user_id: uuid.UUID, source: str = SOURCE
) -> SourceConnection | None:
    result = await session.execute(
        select(SourceConnection).where(
            SourceConnection.user_id == user_id, SourceConnection.source == source
        )
    )
    return result.scalar_one_or_none()


async def count_users(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(AppUser))).scalar_one()
