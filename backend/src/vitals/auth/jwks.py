"""JWKS cache for asymmetrically-signed Supabase tokens.

Newer Supabase projects sign JWTs with a rotating asymmetric key (ES256 by default)
and publish the public half at `/auth/v1/.well-known/jwks.json`. Verification is then
a public-key operation, which is why nothing in this file needs a secret.

Four behaviours are deliberate, and all four are about not letting an upstream problem
become a bigger local one:

* an unknown `kid` triggers at most one refetch, rate-limited by `min_refresh_s` —
  otherwise a garbage `kid` is a free way to make us hammer Supabase's auth endpoint;
* every fetch attempt is subject to that same cooldown, so a JWKS outage costs one
  timeout per minute rather than one per request;
* a fetch failure with a warm cache keeps serving the cached keys, since signing keys
  rotate on the order of months and stale keys still verify real tokens;
* a fetch failure with a cold cache raises `AuthUnavailable` (503), never
  `InvalidToken` (401) — the user's credentials are not the thing that is broken.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import jwt

from vitals.auth.errors import AuthUnavailable, InvalidToken
from vitals.logging import get_logger

log = get_logger(__name__)


class JwksCache:
    def __init__(
        self,
        url: str,
        *,
        ttl_s: int = 600,
        min_refresh_s: int = 60,
        timeout_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.ttl_s = ttl_s
        self.min_refresh_s = min_refresh_s
        self.timeout_s = timeout_s
        self._transport = transport
        self._keys: jwt.PyJWKSet | None = None
        self._fetched_at: float | None = None  # last success — drives the TTL
        self._attempted_at: float | None = None  # last attempt — drives the cooldown
        self._lock = asyncio.Lock()

    async def get_signing_key(self, kid: str | None) -> jwt.PyJWK:
        """Return the public key for `kid`, fetching or refreshing as needed."""
        async with self._lock:
            if self._keys is None or self._expired:
                await self._refresh()

            key = self._lookup(kid)
            if key is not None:
                return key

            # Unknown kid: either a rotation we have not seen yet, or a forged token.
            # One (cooldown-gated) refetch, then a definitive answer.
            if await self._refresh():
                key = self._lookup(kid)
                if key is not None:
                    return key

            raise InvalidToken(f"unknown signing key {kid!r}")

    @property
    def _expired(self) -> bool:
        return self._fetched_at is None or (time.monotonic() - self._fetched_at) > self.ttl_s

    @property
    def _cooling_down(self) -> bool:
        return (
            self._attempted_at is not None
            and (time.monotonic() - self._attempted_at) < self.min_refresh_s
        )

    def _lookup(self, kid: str | None) -> jwt.PyJWK | None:
        if self._keys is None:
            return None
        keys = list(self._keys.keys)
        if kid is None:
            # Tolerated only when the project publishes exactly one key, which is the
            # normal case; with several there is nothing to disambiguate with.
            return keys[0] if len(keys) == 1 else None
        return next((k for k in keys if k.key_id == kid), None)

    async def _refresh(self) -> bool:
        """Fetch the key set. Returns True if the cache was updated.

        Raises `AuthUnavailable` only when there is no usable cache to fall back on.
        """
        if self._cooling_down:
            if self._keys is None:
                raise AuthUnavailable("signing keys are unavailable")
            return False

        self._attempted_at = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s, transport=self._transport
            ) as client:
                response = await client.get(self.url, headers={"accept": "application/json"})
                response.raise_for_status()
            keys = jwt.PyJWKSet.from_dict(response.json())
        except Exception as exc:  # noqa: BLE001 - every failure degrades identically
            log.warning("auth.jwks_refresh_failed", url=self.url, error=str(exc))
            if self._keys is None:
                raise AuthUnavailable("signing keys are unavailable") from exc
            return False

        self._keys = keys
        self._fetched_at = time.monotonic()
        log.info("auth.jwks_refreshed", url=self.url, keys=len(keys.keys))
        return True
