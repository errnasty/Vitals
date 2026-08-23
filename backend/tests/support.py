"""Shared test helpers: settings, tokens and key material, all generated locally.

Nothing here reaches the network, which is the point — the entire auth layer is
verifiable without a Supabase project.
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

from vitals.config import Settings

# 32+ bytes: PyJWT warns below that, and Supabase's real secret is longer still.
SECRET = "test-jwt-secret-value-padded-to-32-bytes"
PROJECT_URL = "https://project.supabase.co"
ISSUER_LOCAL = "https://vitals.local/auth/v1"
USER_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
EMAIL = "owner@example.com"


def local_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "local",
        "supabase_jwt_secret": SECRET,
        "allowed_emails": [],
    }
    base.update(overrides)
    return Settings(**base)


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER_LOCAL,
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
    """A P-256 signing key plus the JWK the fake Supabase JWKS endpoint publishes."""

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
        payload = claims(iss=f"{PROJECT_URL}/auth/v1", **overrides)
        return jwt.encode(payload, self._private, algorithm="ES256", headers={"kid": self.kid})


class FakeJwks:
    """An httpx transport standing in for `/auth/v1/.well-known/jwks.json`."""

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
