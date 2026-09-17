"""Shared test helpers: settings, tokens and key material, all generated locally.

Nothing here reaches the network, which is the point — the entire auth layer is
verifiable with no identity provider in existence. `local_settings` builds the
self-issued deployment (this app signs its own tokens); `external_settings` builds one
that trusts an outside OIDC provider's JWKS.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from vitals.config import SELF_ISSUER, Settings

# 32+ bytes: PyJWT warns below that, and a real signing secret is longer still.
SECRET = "test-jwt-secret-value-padded-to-32-bytes"
# Stands in for any external OIDC provider — Supabase, Auth0, Clerk.
PROJECT_URL = "https://idp.example.com"
ISSUER_EXTERNAL = f"{PROJECT_URL}/auth/v1"
JWKS_URL = f"{ISSUER_EXTERNAL}/.well-known/jwks.json"
ISSUER_SELF = SELF_ISSUER
USER_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
EMAIL = "owner@example.com"


def local_settings(**overrides: Any) -> Settings:
    """A self-issuing deployment: one HS256 secret, no external provider."""
    base: dict[str, Any] = {
        "environment": "local",
        "auth_jwt_secret": SECRET,
        "allowed_emails": [],
    }
    base.update(overrides)
    return Settings(**base)


def external_settings(**overrides: Any) -> Settings:
    """A deployment that trusts an outside provider's JWKS and signs nothing itself."""
    base: dict[str, Any] = {
        "environment": "local",
        "auth_issuer": ISSUER_EXTERNAL,
        "auth_jwks_url": JWKS_URL,
        "auth_jwt_secret": None,
        "allowed_emails": [],
    }
    base.update(overrides)
    return Settings(**base)


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER_SELF,
        "aud": "authenticated",
        "sub": str(USER_ID),
        "email": EMAIL,
        "role": "authenticated",
        "iat": now,
        "exp": now + 3600,
        "session_id": "e3b0c442-9c8f-4f1a-9d2e-3a1b2c3d4e5f",
        "aal": "aal1",
        "amr": [{"method": "magiclink", "timestamp": now}],
        "is_anonymous": False,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def hs256(secret: str = SECRET, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), secret, algorithm="HS256")


class EcKey:
    """A P-256 signing key plus the JWK the fake JWKS endpoint publishes."""

    def __init__(self, kid: str) -> None:
        self.kid = kid
        self._private = ec.generate_private_key(ec.SECP256R1())

    @property
    def jwk(self) -> dict[str, Any]:
        public: dict[str, Any] = json.loads(
            jwt.algorithms.ECAlgorithm.to_jwk(self._private.public_key())
        )
        public.update({"kid": self.kid, "alg": "ES256", "use": "sig"})
        return public

    @property
    def public_pem(self) -> str:
        from cryptography.hazmat.primitives import serialization

        return (
            self._private.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    def sign(self, **overrides: Any) -> str:
        payload = claims(iss=ISSUER_EXTERNAL, **overrides)
        return jwt.encode(payload, self._private, algorithm="ES256", headers={"kid": self.kid})


class FakeJwks:
    """An httpx transport standing in for the provider's `.well-known/jwks.json`."""

    def __init__(self, *keys: EcKey, extra: list[dict[str, Any]] | None = None) -> None:
        self.keys = list(keys)
        self.extra = extra or []
        self.requests = 0
        self.fail = False

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.fail:
            raise httpx.ConnectError("jwks unreachable", request=request)
        return httpx.Response(200, json={"keys": [k.jwk for k in self.keys] + self.extra})


def forge(header: dict[str, Any], payload: dict[str, Any], *, hmac_key: bytes) -> str:
    """Hand-roll a signed JWT, bypassing PyJWT's own guardrails.

    PyJWT refuses to *sign* HS256 with a PEM public key, so an attack that does exactly
    that cannot be built with `jwt.encode`. An attacker has no such scruples, and the
    point of the test is what our verifier does when handed one.
    """
    import hashlib
    import hmac as hmac_module

    def segment(data: dict[str, Any]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    signing_input = f"{segment(header)}.{segment(payload)}"
    signature = hmac_module.new(hmac_key, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
