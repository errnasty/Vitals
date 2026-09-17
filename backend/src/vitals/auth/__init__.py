"""Authentication: bearer JWTs, verified locally on every request.

The token is either self-issued (`vitals auth token`, HS256) or minted by an external
OIDC provider and verified against its JWKS. Either way there is no session state and
no callback to an issuer on the hot path — verification is a signature check plus
claim validation, so the API keeps serving while the issuer is unreachable.
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
