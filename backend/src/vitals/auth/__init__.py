"""Authentication: Supabase-issued JWTs, verified locally on every request.

No session state, no callback into Supabase on the hot path — verification is a
signature check plus claim validation, so the API keeps serving while Supabase Auth
is unreachable.
"""

from vitals.auth.claims import Principal
from vitals.auth.errors import (
    AuthError,
    AuthUnavailable,
    ExpiredToken,
    InvalidToken,
    MissingCredentials,
    NotAllowed,
)
from vitals.auth.jwks import JwksCache
from vitals.auth.users import sync_user
from vitals.auth.verifier import TokenVerifier

__all__ = [
    "AuthError",
    "AuthUnavailable",
    "ExpiredToken",
    "InvalidToken",
    "JwksCache",
    "MissingCredentials",
    "NotAllowed",
    "Principal",
    "TokenVerifier",
    "sync_user",
]
