"""Locally-minted tokens, so the whole API is exercisable with no Supabase project.

These are real HS256 JWTs carrying exactly the claims Supabase issues, verified by
exactly the same code path as production tokens — the only difference is who signed
them. That keeps development honest: if a dev token works and a Supabase token does
not, the difference is the project configuration, not an auth bypass hiding in a
`if settings.environment == "local"` branch somewhere in the request path.

Refused outside `local`. There is no way to mint one on Railway.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import jwt

from vitals.config import Settings

DEV_USER_NAMESPACE = uuid.UUID("6f2f8f1e-2a4a-4b2f-9d3e-1f6f5a7c8b90")
DEFAULT_TTL = timedelta(hours=12)


def dev_user_id(email: str) -> uuid.UUID:
    """Stable per-email id, so re-minting keeps the same local user row."""
    return uuid.uuid5(DEV_USER_NAMESPACE, f"vitals-dev:{email.strip().lower()}")


def mint_dev_token(
    settings: Settings,
    *,
    email: str,
    user_id: uuid.UUID | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> str:
    if not settings.is_local:
        raise RuntimeError(
            f"dev tokens can only be minted locally (environment={settings.environment})"
        )
    if not settings.supabase_jwt_secret:
        raise RuntimeError("SUPABASE_JWT_SECRET must be set to sign dev tokens")

    email = email.strip().lower()
    now = int(time.time())
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id or dev_user_id(email)),
        "email": email,
        "phone": "",
        "role": "authenticated",
        "iat": now,
        "exp": now + int(ttl.total_seconds()),
        "session_id": str(uuid.uuid4()),
        "aal": "aal1",
        "amr": [{"method": "magiclink", "timestamp": now}],
        "is_anonymous": False,
        "app_metadata": {"provider": "email", "providers": ["email"]},
        "user_metadata": {"email": email},
    }
    return jwt.encode(claims, settings.supabase_jwt_secret, algorithm="HS256")
