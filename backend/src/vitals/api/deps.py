"""Shared FastAPI dependencies.

Two identity dependencies, deliberately separate:

* `CurrentPrincipalDep` — the verified token, no database involved. Cheap, and it
  keeps auth working on endpoints that have no business touching Postgres.
* `CurrentUserDep` — the local `app_user` row, provisioned on first sight. Anything
  that reads or writes your data depends on this one.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.auth.claims import Principal
from vitals.auth.errors import MissingCredentials
from vitals.auth.policy import check_allowed, local_bypass_principal
from vitals.auth.users import sync_user
from vitals.auth.verifier import TokenVerifier
from vitals.config import Settings, get_settings
from vitals.db.models import AppUser
from vitals.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False so a missing header raises our own error shape rather than
# FastAPI's, and so `WWW-Authenticate` carries the reason.
_bearer = HTTPBearer(auto_error=False, description="Supabase access token")
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


@lru_cache
def get_verifier() -> TokenVerifier:
    """One verifier per process: the JWKS cache it owns is the point."""
    return TokenVerifier(get_settings())


async def current_principal(credentials: BearerDep, settings: SettingsDep) -> Principal:
    if settings.auth_disabled and settings.is_local:
        return local_bypass_principal()

    if credentials is None or not credentials.credentials:
        raise MissingCredentials("expected an 'Authorization: Bearer <token>' header")

    principal = await get_verifier().verify(credentials.credentials)
    check_allowed(settings, principal)
    return principal


CurrentPrincipalDep = Annotated[Principal, Depends(current_principal)]


async def current_user(principal: CurrentPrincipalDep, session: SessionDep) -> AppUser:
    return await sync_user(session, principal)


CurrentUserDep = Annotated[AppUser, Depends(current_user)]
