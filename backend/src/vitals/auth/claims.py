"""The verified identity, decoupled from Supabase's claim names.

Everything downstream depends on `Principal`, never on a raw claims dict, so swapping
or adding an identity provider later is a change in one file rather than a sweep.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from vitals.auth.errors import InvalidToken

# Supabase stamps `role` on every token it issues. `service_role` tokens are the
# project's admin key: authentic, but emphatically not a user, and they must never
# authenticate a request as one.
USER_ROLES = frozenset({"authenticated"})


def _timestamp(claims: Mapping[str, Any], name: str) -> datetime:
    value = claims.get(name)
    if not isinstance(value, int | float):
        raise InvalidToken(f"claim '{name}' is missing or not a timestamp")
    return datetime.fromtimestamp(float(value), tz=UTC)


@dataclass(frozen=True, slots=True)
class Principal:
    """A caller whose token has been cryptographically verified."""

    user_id: uuid.UUID
    email: str | None
    role: str
    issued_at: datetime
    expires_at: datetime
    session_id: str | None = None
    # Assurance level (aal1 = password/magic link, aal2 = MFA) and the methods used.
    assurance_level: str | None = None
    auth_methods: tuple[str, ...] = ()
    is_anonymous: bool = False
    claims: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any]) -> Principal:
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise InvalidToken("claim 'sub' is missing")
        try:
            user_id = uuid.UUID(subject)
        except ValueError as exc:
            raise InvalidToken("claim 'sub' is not a uuid") from exc

        role = claims.get("role")
        if not isinstance(role, str) or role not in USER_ROLES:
            raise InvalidToken(f"role {role!r} may not authenticate as a user")

        if claims.get("is_anonymous") is True:
            raise InvalidToken("anonymous sessions are not accepted")

        email = claims.get("email")
        if email is not None and not isinstance(email, str):
            raise InvalidToken("claim 'email' is not a string")

        amr = claims.get("amr")
        methods: tuple[str, ...] = ()
        if isinstance(amr, list):
            methods = tuple(
                str(entry.get("method"))
                for entry in amr
                if isinstance(entry, dict) and entry.get("method")
            )

        session_id = claims.get("session_id")
        assurance = claims.get("aal")
        return cls(
            user_id=user_id,
            email=email.lower() if email else None,
            role=role,
            issued_at=_timestamp(claims, "iat"),
            expires_at=_timestamp(claims, "exp"),
            session_id=session_id if isinstance(session_id, str) else None,
            assurance_level=assurance if isinstance(assurance, str) else None,
            auth_methods=methods,
            is_anonymous=False,
            claims=dict(claims),
        )
