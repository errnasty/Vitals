"""Identity endpoints.

`/auth/me` is the frontend's "am I signed in, and as whom" call, and doubles as the
proof that the whole chain works: Supabase issues a token, the API verifies it, the
allowlist accepts it, and a local user row exists to hang phase-2 data off.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from vitals.api.deps import CurrentPrincipalDep, CurrentUserDep

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenInfo(BaseModel):
    """What the presented token proves — useful for debugging a login that 'works'."""

    role: str
    issued_at: datetime
    expires_at: datetime
    assurance_level: str | None
    auth_methods: list[str]
    session_id: str | None


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    display_name: str | None
    timezone: str
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None
    token: TokenInfo


@router.get("/me", summary="The authenticated user")
async def me(user: CurrentUserDep, principal: CurrentPrincipalDep) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        is_active=user.is_active,
        created_at=user.created_at,
        last_seen_at=user.last_seen_at,
        token=TokenInfo(
            role=principal.role,
            issued_at=principal.issued_at,
            expires_at=principal.expires_at,
            assurance_level=principal.assurance_level,
            auth_methods=list(principal.auth_methods),
            session_id=principal.session_id,
        ),
    )
