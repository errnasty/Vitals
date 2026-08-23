"""Authentication failures, as a small closed set with deliberate status codes.

The distinction that matters operationally: a token we cannot *verify* is 401, but a
token we cannot verify *because Supabase is unreachable* is 503. Returning 401 for an
outage would log a legitimate user out and send them into a re-login loop against the
very service that is down.
"""

from __future__ import annotations


class AuthError(Exception):
    """Base class. `code` is stable and machine-readable; `detail` is for humans."""

    status_code = 401
    code = "unauthorized"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class MissingCredentials(AuthError):
    code = "missing_credentials"


class InvalidToken(AuthError):
    code = "invalid_token"


class ExpiredToken(AuthError):
    code = "token_expired"


class NotAllowed(AuthError):
    """Authentic token, but this identity may not use this deployment."""

    status_code = 403
    code = "forbidden"


class AuthUnavailable(AuthError):
    """Verification could not be attempted — misconfiguration or an upstream outage."""

    status_code = 503
    code = "auth_unavailable"
