"""Verification of HS256 (self-issued) tokens, and everything that must be rejected."""

from __future__ import annotations

import base64
import json
import time
import uuid

import pytest

from tests.support import (
    EMAIL,
    ISSUER_EXTERNAL,
    PROJECT_URL,
    SECRET,
    USER_ID,
    claims,
    external_settings,
    hs256,
    local_settings,
)
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


async def test_rejects_another_issuers_token() -> None:
    with pytest.raises(InvalidToken, match="another issuer"):
        await _verifier().verify(hs256(iss="https://evil.example.com/auth/v1"))


async def test_rejects_an_unexpected_audience() -> None:
    # aud=authenticated marks an end-user token; anything else is not one.
    with pytest.raises(InvalidToken, match="audience"):
        await _verifier().verify(hs256(aud="anon"))


async def test_rejects_a_service_role_token() -> None:
    """An admin/machine key is authentic, and must never authenticate as a user."""
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
    verifier = TokenVerifier(local_settings(auth_jwt_secret=None))
    with pytest.raises(AuthUnavailable):
        await verifier.verify(hs256())


async def test_rejects_hs256_when_only_asymmetric_verification_is_configured() -> None:
    verifier = TokenVerifier(external_settings())
    with pytest.raises(InvalidToken, match="no shared secret"):
        await verifier.verify(hs256(iss=ISSUER_EXTERNAL))


async def test_issuer_and_jwks_come_from_the_auth_settings() -> None:
    settings = external_settings()
    assert settings.jwt_issuer == ISSUER_EXTERNAL
    assert settings.jwks_url == f"{ISSUER_EXTERNAL}/.well-known/jwks.json"
    assert settings.self_issued is False


async def test_a_legacy_supabase_url_still_configures_both() -> None:
    """An existing .env keeps working; `vitals doctor` is what points at the rename."""
    settings = local_settings(supabase_url=f"{PROJECT_URL}/")

    assert settings.jwt_issuer == f"{PROJECT_URL}/auth/v1"
    assert settings.jwks_url == f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"
    assert settings.legacy_supabase_env == ["SUPABASE_URL"]

    principal = await TokenVerifier(settings).verify(
        hs256(iss=f"{PROJECT_URL}/auth/v1", sub=str(uuid.uuid4()))
    )
    assert principal.role == "authenticated"


async def test_self_issued_tokens_verify_through_the_production_path() -> None:
    """A minted token is not a bypass — it goes through the same verifier."""
    from vitals.auth.tokens import mint_token, self_user_id

    settings = local_settings()
    principal = await TokenVerifier(settings).verify(mint_token(settings, email=EMAIL))

    assert principal.user_id == self_user_id(EMAIL)
    assert principal.email == EMAIL


async def test_self_issued_tokens_can_be_minted_in_production() -> None:
    """With no external provider there is no issuer to forge: this is the login."""
    from vitals.auth.tokens import mint_token

    settings = local_settings(
        environment="production", auth_jwt_secret=SECRET, allowed_emails=[EMAIL]
    )
    assert settings.self_issued is True

    principal = await TokenVerifier(settings).verify(mint_token(settings, email=EMAIL))
    assert principal.email == EMAIL


async def test_minting_is_refused_against_an_external_issuer() -> None:
    """Signing someone else's `iss` here would be a forgery, not a convenience."""
    from vitals.auth.tokens import MintRefused, mint_token

    settings = external_settings(
        environment="production", auth_jwt_secret=SECRET, allowed_emails=[EMAIL]
    )
    with pytest.raises(MintRefused, match="external issuer"):
        mint_token(settings, email=EMAIL)


async def test_minting_is_refused_for_an_address_outside_the_allowlist() -> None:
    """A token every request would 403 on is worse than no token at all."""
    from vitals.auth.tokens import MintRefused, mint_token

    settings = local_settings(allowed_emails=[EMAIL])
    with pytest.raises(MintRefused, match="VITALS_ALLOWED_EMAILS"):
        mint_token(settings, email="stranger@example.com")


async def test_minting_is_refused_without_a_signing_key() -> None:
    from vitals.auth.tokens import MintRefused, mint_token

    with pytest.raises(MintRefused, match="VITALS_AUTH_JWT_SECRET"):
        mint_token(local_settings(auth_jwt_secret=None), email=EMAIL)
