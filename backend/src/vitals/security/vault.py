"""Credential storage behind a protocol, so phase 12 is a swap rather than a refactor.

The key lives only in the Railway environment; the ciphertext lives only in Supabase.
Neither half is sufficient, so a database compromise alone does not surrender the
Garmin account — which is the entire reason these are not plain columns.

`CredentialVault` is the seam. Today `EncryptedDbVault` encrypts everything under one
deployment key. Multi-user later swaps in per-user envelope encryption without touching
a single caller.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any, Protocol, cast

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.config import Settings
from vitals.db.models import Credential


class VaultUnavailable(RuntimeError):
    """No usable encryption key — refuse rather than store a secret in the clear."""


class CredentialVault(Protocol):
    async def get(self, user_id: uuid.UUID, name: str) -> str | None: ...

    async def put(self, user_id: uuid.UUID, name: str, value: str) -> bool: ...

    async def delete(self, user_id: uuid.UUID, name: str) -> bool: ...


class EncryptedDbVault:
    """Fernet (AES-128-CBC + HMAC) over rows in `credential`."""

    def __init__(self, session: AsyncSession, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise VaultUnavailable(
                "VITALS_ENCRYPTION_KEY is not a valid Fernet key; generate one with "
                '`python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"`'
            ) from exc
        self._key = key
        self._session = session

    def _fingerprint(self, value: str) -> str:
        """Keyed digest of the plaintext.

        Keyed rather than a bare hash: it lets a sync detect "the token changed" without
        decrypting, while a leaked database on its own cannot be dictionary-attacked to
        recover a short secret such as a password.
        """
        return hmac.new(self._key.encode(), value.encode(), hashlib.sha256).hexdigest()

    async def _row(self, user_id: uuid.UUID, name: str) -> Credential | None:
        result = await self._session.execute(
            select(Credential).where(Credential.user_id == user_id, Credential.name == name)
        )
        return result.scalar_one_or_none()

    async def get(self, user_id: uuid.UUID, name: str) -> str | None:
        row = await self._row(user_id, name)
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row.ciphertext.encode()).decode()
        except InvalidToken as exc:
            # Almost always a rotated or mismatched VITALS_ENCRYPTION_KEY. Say so
            # plainly: silently treating it as "no credential" would trigger a fresh
            # SSO login from whatever host noticed, which is the outcome to avoid.
            raise VaultUnavailable(
                f"credential {name!r} cannot be decrypted with the current VITALS_ENCRYPTION_KEY"
            ) from exc

    async def put(self, user_id: uuid.UUID, name: str, value: str) -> bool:
        """Store `value`. Returns True when it differed from what was already stored."""
        fingerprint = self._fingerprint(value)
        row = await self._row(user_id, name)
        if row is not None and hmac.compare_digest(row.fingerprint, fingerprint):
            return False

        ciphertext = self._fernet.encrypt(value.encode()).decode()
        if row is None:
            self._session.add(
                Credential(
                    user_id=user_id, name=name, ciphertext=ciphertext, fingerprint=fingerprint
                )
            )
        else:
            row.ciphertext = ciphertext
            row.fingerprint = fingerprint
        await self._session.commit()
        return True

    async def delete(self, user_id: uuid.UUID, name: str) -> bool:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                delete(Credential).where(Credential.user_id == user_id, Credential.name == name)
            ),
        )
        await self._session.commit()
        return bool(result.rowcount)


def build_vault(session: AsyncSession, settings: Settings) -> EncryptedDbVault:
    if not settings.encryption_key:
        raise VaultUnavailable(
            "VITALS_ENCRYPTION_KEY is not set; Garmin credentials cannot be stored"
        )
    return EncryptedDbVault(session, settings.encryption_key)
