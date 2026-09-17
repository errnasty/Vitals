"""Tokens this deployment issues to itself.

A single-user health app does not need an identity provider. When no external issuer
is configured, Vitals *is* the issuer: `vitals auth token` mints a real HS256 JWT,
signed with `VITALS_AUTH_JWT_SECRET`, carrying exactly the claims the verifier
demands — and that token is then verified by exactly the same code path an external
provider's token would take.

That symmetry is the point. There is no `if environment == "local"` branch hiding an
auth bypass in the request path: a self-issued token is accepted because its signature
and claims check out, not because of where it came from.

Minting is refused whenever an external provider *is* configured (outside local
development), because there the issuer is someone else and a token signed here would
be a forgery of their `iss`.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import jwt

from vitals.config import Settings

SELF_USER_NAMESPACE = uuid.UUID("6f2f8f1e-2a4a-4b2f-9d3e-1f6f5a7c8b90")
DEFAULT_TTL = timedelta(hours=12)


class MintRefused(RuntimeError):
    """This deployment is not entitled to sign the token that was asked for."""


def self_user_id(email: str) -> uuid.UUID:
    """Stable per-email id, so re-minting keeps the same `app_user` row."""
    return uuid.uuid5(SELF_USER_NAMESPACE, f"vitals-dev:{email.strip().lower()}")


def mint_token(
    settings: Settings,
    *,
    email: str,
    user_id: uuid.UUID | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> str:
    """Sign an access token for `email`.

    Raises `MintRefused` rather than producing a token that cannot work: one signed
    against someone else's issuer, one with no key to sign it, or one for an address
    the allowlist would reject on the very next request.
    """
    if not settings.is_local and not settings.self_issued:
        raise MintRefused(
            "this deployment verifies tokens from an external issuer "
            f"({settings.jwt_issuer}); get the token from there, not from here"
        )
    if not settings.jwt_secret:
        raise MintRefused("VITALS_AUTH_JWT_SECRET must be set to sign tokens")

    email = email.strip().lower()
    if settings.allowed_emails and email not in settings.allowed_emails:
        raise MintRefused(
            f"{email} is not in VITALS_ALLOWED_EMAILS, so every request with this token "
            "would be rejected with 403"
        )

    now = int(time.time())
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id or self_user_id(email)),
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
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
