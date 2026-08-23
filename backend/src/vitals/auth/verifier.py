"""Supabase access-token verification.

Supabase signs end-user JWTs one of two ways, and both are supported here:

* **legacy projects** — HS256 with the project's shared `SUPABASE_JWT_SECRET`;
* **current projects** — an asymmetric key (ES256 by default) whose public half is
  published as JWKS.

The header's `alg` selects which *path* runs, but never the algorithm a key is
verified with: the HMAC path only ever uses the shared secret with `["HS256"]`, and
the asymmetric path only ever uses a JWKS key with that key's own declared algorithm.
That is the fix for the classic algorithm-confusion attack, where a token is signed
with HS256 using a *public* key the attacker also knows, and a naive verifier that
trusts the header happily accepts it.
"""

from __future__ import annotations

from typing import Any

import jwt

from vitals.auth.claims import Principal
from vitals.auth.errors import AuthUnavailable, ExpiredToken, InvalidToken
from vitals.auth.jwks import JwksCache
from vitals.config import Settings

# Supabase's legacy signing scheme is HS256 and nothing else.
HMAC_ALGORITHMS = frozenset({"HS256"})
ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "EdDSA"})

# Claims we refuse to infer a default for. `sub` identifies the user, `exp` bounds the
# damage of a leaked token, `aud`/`iss` scope it to this project.
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]


class TokenVerifier:
    """Verifies a bearer token and returns the identity it proves."""

    def __init__(self, settings: Settings, *, jwks: JwksCache | None = None) -> None:
        self._settings = settings
        self._secret = settings.supabase_jwt_secret
        if jwks is None and settings.jwks_url:
            jwks = JwksCache(
                settings.jwks_url,
                ttl_s=settings.jwks_ttl_s,
                min_refresh_s=settings.jwks_min_refresh_s,
                timeout_s=settings.jwks_timeout_s,
            )
        self._jwks = jwks

    async def verify(self, token: str) -> Principal:
        token = token.strip()
        if not token:
            raise InvalidToken("empty token")
        if not self._secret and self._jwks is None:
            raise AuthUnavailable("no token verification method is configured")

        header = self._header(token)
        algorithm = header.get("alg")
        if not isinstance(algorithm, str):
            raise InvalidToken("token header has no algorithm")

        if algorithm in HMAC_ALGORITHMS:
            key, algorithms = self._hmac_key()
        elif algorithm in ASYMMETRIC_ALGORITHMS:
            key, algorithms = await self._public_key(header.get("kid"))
        else:
            # Catches "none" and every other unsupported or downgrade algorithm.
            raise InvalidToken(f"unsupported algorithm {algorithm!r}")

        claims = self._decode(token, key=key, algorithms=algorithms)
        return Principal.from_claims(claims)

    @staticmethod
    def _header(token: str) -> dict[str, Any]:
        try:
            return jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidToken("malformed token") from exc

    def _hmac_key(self) -> tuple[Any, list[str]]:
        if not self._secret:
            raise InvalidToken("token is HS256-signed but no shared secret is configured")
        return self._secret, sorted(HMAC_ALGORITHMS)

    async def _public_key(self, kid: object) -> tuple[Any, list[str]]:
        if self._jwks is None:
            raise InvalidToken("token is asymmetrically signed but no JWKS URL is configured")
        if kid is not None and not isinstance(kid, str):
            raise InvalidToken("token header has a malformed key id")

        signing_key = await self._jwks.get_signing_key(kid)
        # Defence in depth: a symmetric key served from a key set would let the header
        # pick HMAC verification against a value an attacker can read.
        if signing_key.algorithm_name not in ASYMMETRIC_ALGORITHMS:
            raise InvalidToken(f"signing key {kid!r} is not an asymmetric key")
        return signing_key.key, [signing_key.algorithm_name]

    def _decode(self, token: str, *, key: Any, algorithms: list[str]) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=algorithms,
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                leeway=self._settings.jwt_leeway_s,
                options={"require": REQUIRED_CLAIMS, "verify_aud": True, "verify_iss": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ExpiredToken("token has expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise InvalidToken("token is not valid yet") from exc
        except jwt.InvalidAudienceError as exc:
            raise InvalidToken("token was not issued for this audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise InvalidToken("token was issued by another project") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise InvalidToken(f"token is missing claim '{exc.claim}'") from exc
        except jwt.InvalidSignatureError as exc:
            raise InvalidToken("token signature does not match") from exc
        except jwt.PyJWTError as exc:
            raise InvalidToken("token could not be verified") from exc
        return claims
