"""Who may use this deployment, and whether it is safe to serve at all.

The allowlist is the gate that does not depend on how tokens are issued. Self-issued
tokens are only ever minted by you, but an external provider's sign-up policy is a
dashboard toggle away from letting the world in — and the failure mode of that
regressing silently is a public health app anyone can create an account on. So the
check lives here, in this repository, reviewable and covered by tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from vitals.auth.claims import Principal
from vitals.auth.errors import NotAllowed
from vitals.config import Settings

# The identity requests run as when auth is switched off locally.
LOCAL_BYPASS_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
LOCAL_BYPASS_EMAIL = "dev@vitals.local"


class AuthNotReady(RuntimeError):
    """Raised at startup — never at request time — when the deployment is unsafe."""


def assert_auth_ready(settings: Settings) -> None:
    """Fail the deploy rather than serve health data unprotected.

    Local development is exempt: the whole point of `local` is being able to run the
    stack with nothing configured.
    """
    if settings.is_local:
        return

    problems: list[str] = []
    if settings.auth_disabled:
        problems.append("VITALS_AUTH_DISABLED is set outside local development")
    if not settings.auth_configured:
        problems.append("neither VITALS_AUTH_JWT_SECRET nor VITALS_AUTH_JWKS_URL is set")
    if not settings.allowed_emails:
        problems.append(
            "VITALS_ALLOWED_EMAILS is empty, so any account the issuer accepts would be let in"
        )

    if problems:
        raise AuthNotReady(
            "refusing to start with authentication misconfigured: " + "; ".join(problems)
        )


def check_allowed(settings: Settings, principal: Principal) -> None:
    """Reject an authentic token belonging to someone who is not you."""
    if not settings.allowed_emails:
        return  # Only reachable locally: `assert_auth_ready` blocks this elsewhere.
    if principal.email is None or principal.email.lower() not in settings.allowed_emails:
        raise NotAllowed("this account is not permitted on this deployment")


def local_bypass_principal() -> Principal:
    """The principal used when VITALS_AUTH_DISABLED is set (local only)."""
    now = datetime.now(UTC)
    return Principal(
        user_id=LOCAL_BYPASS_USER_ID,
        email=LOCAL_BYPASS_EMAIL,
        role="authenticated",
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        assurance_level="aal1",
        claims={"sub": str(LOCAL_BYPASS_USER_ID), "email": LOCAL_BYPASS_EMAIL},
    )
