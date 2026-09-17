"""Verification of asymmetrically-signed tokens — how an external OIDC provider signs.

These tests never reach the network: an httpx MockTransport plays the part of the
provider's `.well-known/jwks.json`, which is what makes the whole JWKS path — rotation,
caching, outages, and the algorithm-confusion defence — developable with no identity
provider in existence.
"""

from __future__ import annotations

import jwt
import pytest

from tests.support import (
    ISSUER_EXTERNAL,
    SECRET,
    EcKey,
    FakeJwks,
    claims,
    external_settings,
    forge,
)
from vitals.auth.errors import AuthUnavailable, InvalidToken
from vitals.auth.jwks import JwksCache
from vitals.auth.verifier import TokenVerifier


def _verifier(jwks: FakeJwks, *, ttl_s: int = 600, min_refresh_s: int = 60, **overrides: object):
    settings = external_settings(**overrides)
    cache = JwksCache(
        settings.jwks_url or "",
        ttl_s=ttl_s,
        min_refresh_s=min_refresh_s,
        transport=jwks.transport,
    )
    return TokenVerifier(settings, jwks=cache)


async def test_verifies_an_es256_token() -> None:
    key = EcKey("key-1")
    jwks = FakeJwks(key)

    principal = await _verifier(jwks).verify(key.sign())

    assert principal.email == "owner@example.com"
    assert jwks.requests == 1


async def test_keys_are_cached_across_requests() -> None:
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    verifier = _verifier(jwks)

    await verifier.verify(key.sign())
    await verifier.verify(key.sign())

    assert jwks.requests == 1


async def test_expired_cache_is_refreshed() -> None:
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    verifier = _verifier(jwks, ttl_s=0, min_refresh_s=0)

    await verifier.verify(key.sign())
    await verifier.verify(key.sign())

    assert jwks.requests == 2


async def test_key_rotation_is_picked_up() -> None:
    """A token signed by a key we have never seen must still verify after a refetch."""
    old, new = EcKey("key-old"), EcKey("key-new")
    jwks = FakeJwks(old)
    verifier = _verifier(jwks, min_refresh_s=0)

    await verifier.verify(old.sign())
    jwks.keys.append(new)

    assert await verifier.verify(new.sign())
    assert jwks.requests == 2


async def test_unknown_kid_does_not_hammer_the_issuer() -> None:
    """An attacker-chosen `kid` must not be a free refetch on every request."""
    key, stranger = EcKey("key-1"), EcKey("key-unknown")
    jwks = FakeJwks(key)
    verifier = _verifier(jwks, min_refresh_s=3600)

    await verifier.verify(key.sign())
    for _ in range(5):
        with pytest.raises(InvalidToken, match="unknown signing key"):
            await verifier.verify(stranger.sign())

    assert jwks.requests == 1


async def test_cold_cache_outage_is_503_not_401() -> None:
    """The provider being down must not look like the user's token being wrong."""
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    jwks.fail = True

    with pytest.raises(AuthUnavailable):
        await _verifier(jwks).verify(key.sign())


async def test_warm_cache_survives_an_outage() -> None:
    """Signing keys rotate monthly; a JWKS blip must not sign everyone out."""
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    verifier = _verifier(jwks, ttl_s=0, min_refresh_s=0)

    await verifier.verify(key.sign())
    jwks.fail = True

    assert await verifier.verify(key.sign())


async def test_outage_retries_are_rate_limited() -> None:
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    jwks.fail = True
    cache = JwksCache("https://idp.example.com/jwks", min_refresh_s=3600, transport=jwks.transport)

    for _ in range(4):
        with pytest.raises(AuthUnavailable):
            await cache.get_signing_key("key-1")

    assert jwks.requests == 1


async def test_rejects_a_token_signed_with_the_public_key() -> None:
    """The algorithm-confusion attack: HS256 signed with the *public* key everyone can read.

    A verifier that trusts the header's `alg` would hand the public key to the HMAC
    algorithm and accept this. Here the HMAC path only ever uses the shared secret, so
    the token is rejected whether or not one is configured.
    """
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    forged = forge(
        {"alg": "HS256", "typ": "JWT", "kid": "key-1"},
        claims(iss=ISSUER_EXTERNAL),
        hmac_key=key.public_pem.encode(),
    )

    with pytest.raises(InvalidToken, match="no shared secret"):
        await _verifier(jwks).verify(forged)

    with pytest.raises(InvalidToken, match="signature"):
        await _verifier(jwks, auth_jwt_secret=SECRET).verify(forged)


async def test_rejects_a_symmetric_key_served_from_the_key_set() -> None:
    """Defence in depth: an `oct` key in a JWKS is never valid signing material here."""
    key = EcKey("key-1")
    jwks = FakeJwks(key, extra=[{"kty": "oct", "kid": "sneaky", "k": "c2VjcmV0LXZhbHVl"}])
    # Presented as ES256 so it takes the asymmetric path and reaches the key-type check
    # rather than being turned away earlier for being HS256.
    forged = forge(
        {"alg": "ES256", "typ": "JWT", "kid": "sneaky"},
        claims(iss=ISSUER_EXTERNAL),
        hmac_key=b"secret-value",
    )

    with pytest.raises(InvalidToken, match="not an asymmetric key"):
        await _verifier(jwks).verify(forged)


async def test_single_key_sets_tolerate_a_missing_kid() -> None:
    key = EcKey("key-1")
    jwks = FakeJwks(key)
    token = jwt.encode(claims(iss=ISSUER_EXTERNAL), key._private, algorithm="ES256")

    assert await _verifier(jwks).verify(token)


async def test_multi_key_sets_require_a_kid() -> None:
    first, second = EcKey("key-1"), EcKey("key-2")
    jwks = FakeJwks(first, second)
    token = jwt.encode(claims(iss=ISSUER_EXTERNAL), first._private, algorithm="ES256")

    with pytest.raises(InvalidToken, match="unknown signing key"):
        await _verifier(jwks).verify(token)
