"""Just-in-time provisioning of the local user row.

Called on every authenticated request that needs the database. The write is throttled:
`last_seen_at` is only touched when it is already stale, so ordinary traffic is a
single indexed SELECT rather than a write per request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.auth.claims import Principal
from vitals.auth.errors import NotAllowed
from vitals.db.models import AppUser
from vitals.logging import get_logger

log = get_logger(__name__)

SEEN_INTERVAL = timedelta(minutes=5)


async def sync_user(session: AsyncSession, principal: Principal) -> AppUser:
    """Return the `app_user` row for this principal, creating it on first sight."""
    user = await session.get(AppUser, principal.user_id)
    if user is None:
        user = await _create(session, principal)
    else:
        await _refresh(session, user, principal)

    if not user.is_active:
        # A local kill switch that keeps working when Supabase is unreachable.
        raise NotAllowed("this account is disabled")
    return user


async def _create(session: AsyncSession, principal: Principal) -> AppUser:
    user = AppUser(
        id=principal.user_id,
        email=principal.email,
        last_seen_at=datetime.now(UTC),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()

        # Two concurrent first requests: the other one won, and its row is the answer.
        existing = await session.get(AppUser, principal.user_id)
        if existing is not None:
            return existing

        # Or the address is already attached to a different id — a Supabase account
        # deleted and recreated. Silently moving the email would orphan the old
        # account's history, so refuse and let a human decide which row is real.
        clash = (
            await session.execute(select(AppUser).where(AppUser.email == principal.email))
        ).scalar_one_or_none()
        if clash is not None:
            log.error(
                "auth.email_belongs_to_another_user",
                user_id=str(principal.user_id),
                existing_user_id=str(clash.id),
            )
            raise NotAllowed("this address is already registered to another account") from None
        raise
    log.info("auth.user_provisioned", user_id=str(user.id))
    return user


async def _refresh(session: AsyncSession, user: AppUser, principal: Principal) -> None:
    now = datetime.now(UTC)
    changed = False

    if principal.email and principal.email != user.email:
        user.email = principal.email
        changed = True

    seen = user.last_seen_at
    if seen is None or (now - _aware(seen)) > SEEN_INTERVAL:
        user.last_seen_at = now
        changed = True

    if changed:
        await session.commit()


def _aware(value: datetime) -> datetime:
    """SQLite (tests) hands back naive datetimes; Postgres does not."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
