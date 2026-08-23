"""Verification of HS256 (legacy Supabase) tokens, and everything that must be rejected."""

from __future__ import annotations

import base64
import json
import time
import uuid

import pytest

from tests.support import EMAIL, PROJECT_URL, SECRET, USER_ID, claims, hs256, local_settings
from vitals.auth.errors import AuthUnavailable, ExpiredToken, InvalidToken
from vitals.auth.verifier import TokenVerifier


def _verifier(**overrides: object) -> TokenVerifier:
    return TokenVerifier(local_settings(**overrides))


async def test_accepts_a_well_formed_token() -> None:
    principal = await _verifier().verify(hs256())

    assert principal.user_id == USER_ID
    assert principal.email == EMAIL
    assert principal.role == "authenticated"
    assert principal.assurance_level == "aal1"
    assert principal.auth_methods == ("magiclink",)


async def test_email_is_normalised_to_lowercase() -> None:
    principal = await _verifier().verify(hs256(email="Owner@Example.COM"))
    assert principal.email == EMAIL


async def test_bearer_whitespace_is_tolerated() -> None:
    assert await _verifier().verify(f"  {hs256()}  ")


async def test_rejects_an_expired_token() -> None:
    now = int(time.time())
    with pytest.raises(ExpiredToken):
        await _verifier().verify(hs256(iat=now - 7200, exp=now - 3600))


async def test_accepts_a_token_expiring_inside_the_leeway() -> None:
    now = int(time.time())
    principal = await _verifier(jwt_leeway_s=30).verify(hs256(iat=now - 3600, exp=now - 5))
    assert principal.user_id == USER_ID


async def test_rejects_a_forged_signature() -> None:
    with pytest.raises(InvalidToken, match="signature"):
        await _verifier().verify(hs256(secret="a-different-secret"))


async def test_rejects_another_projects_issuer() -> None:
    with pytest.raises(InvalidToken, match="another project"):
        await _verifier().verify(hs256(iss="https://evil.supabase.co/auth/v1"))


async def test_rejects_an_unexpected_audience() -> None:
    # Supabase stamps aud=authenticated on user tokens; anything else is not one.
    with pytest.raises(InvalidToken, match="audience"):
        await _verifier().verify(hs256(aud="anon"))


async def test_rejects_a_service_role_token() -> None:
    """The project's admin key is authentic, and must never authenticate as a user."""
    with pytest.raises(InvalidToken, match="may not authenticate"):
        await _verifier().verify(hs256(role="service_role"))


async def test_rejects_an_anonymous_session() -> None:
    with pytest.raises(InvalidToken, match="anonymous"):
        await _verifier().verify(hs256(is_anonymous=True))


@pytest.mark.parametrize("claim", ["sub", "exp", "iat", "iss", "aud"])
async def test_rejects_a_token_missing_a_required_claim(claim: str) -> None:
    with pytest.raises(InvalidToken):
        await _verifier().verify(hs256(**{claim: None}))


async def test_rejects_a_non_uuid_subject() -> None:
    with pytest.raises(InvalidToken, match="not a uuid"):
        await _verifier().verify(hs256(sub="not-a-uuid"))


async def test_rejects_an_unsigned_token() -> None:
    """`alg: none` is the oldest JWT attack there is."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = base64.urlsafe_b64encode(json.dumps(claims()).encode())
    token = f"{header.decode().rstrip('=')}.{payload.decode().rstrip('=')}."

    with pytest.raises(InvalidToken, match="unsupported algorithm"):
        await _verifier().verify(token)


@pytest.mark.parametrize("token", ["", "   ", "not.a.jwt", "garbage"])
async def test_rejects_malformed_input(token: str) -> None:
    with pytest.raises(InvalidToken):
        await _verifier().verify(token)


async def test_reports_unavailable_when_nothing_is_configured() -> None:
    """A misconfigured deployment is 503, not 401: the credentials are not the problem."""
    verifier = TokenVerifier(local_settings(supabase_jwt_secret=None))
    with pytest.raises(AuthUnavailable):
        await verifier.verify(hs256())


async def test_rejects_hs256_when_only_asymmetric_verification_is_configured() -> None:
    verifier = TokenVerifier(local_settings(supabase_jwt_secret=None, supabase_url=PROJECT_URL))
    with pytest.raises(InvalidToken, match="no shared secret"):
        await verifier.verify(hs256(iss=f"{PROJECT_URL}/auth/v1"))


async def test_issuer_is_derived_from_the_supabase_url() -> None:
    settings = local_settings(supabase_url=f"{PROJECT_URL}/")
    assert settings.jwt_issuer == f"{PROJECT_URL}/auth/v1"
    assert settings.jwks_url == f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"

    principal = await TokenVerifier(settings).verify(
        hs256(iss=f"{PROJECT_URL}/auth/v1", sub=str(uuid.uuid4()))
    )
    assert principal.role == "authenticated"


async def test_dev_tokens_verify_through_the_production_path() -> None:
    """Local tokens are not a bypass — they go through the same verifier."""
    from vitals.auth.dev import dev_user_id, mint_dev_token

    settings = local_settings()
    principal = await TokenVerifier(settings).verify(mint_dev_token(settings, email=EMAIL))

    assert principal.user_id == dev_user_id(EMAIL)
    assert principal.email == EMAIL


async def test_dev_tokens_cannot_be_minted_outside_local() -> None:
    from vitals.auth.dev import mint_dev_token

    settings = local_settings(environment="production", supabase_jwt_secret=SECRET)
    with pytest.raises(RuntimeError, match="only be minted locally"):
        mint_dev_token(settings, email=EMAIL)
