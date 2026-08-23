"""Encrypted credential storage."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import GARMIN_TOKENS, AppUser, Credential
from vitals.security.vault import EncryptedDbVault, VaultUnavailable, build_vault

KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()
TOKENS = '{"di_token": "abc", "di_refresh_token": "def", "di_client_id": "ghi"}'


async def test_round_trip(pg_session: AsyncSession, pg_user: AppUser) -> None:
    vault = EncryptedDbVault(pg_session, KEY)

    assert await vault.put(pg_user.id, GARMIN_TOKENS, TOKENS) is True
    assert await vault.get(pg_user.id, GARMIN_TOKENS) == TOKENS


async def test_nothing_is_stored_in_the_clear(pg_session: AsyncSession, pg_user: AppUser) -> None:
    await EncryptedDbVault(pg_session, KEY).put(pg_user.id, GARMIN_TOKENS, TOKENS)

    row = (await pg_session.execute(select(Credential))).scalar_one()
    assert "di_refresh_token" not in row.ciphertext
    assert TOKENS not in row.ciphertext


async def test_storing_an_unchanged_value_is_a_no_op(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """Every sync writes the tokens back; only a real refresh should touch the row."""
    vault = EncryptedDbVault(pg_session, KEY)
    await vault.put(pg_user.id, GARMIN_TOKENS, TOKENS)

    assert await vault.put(pg_user.id, GARMIN_TOKENS, TOKENS) is False
    assert await vault.put(pg_user.id, GARMIN_TOKENS, TOKENS + " ") is True


async def test_the_fingerprint_is_keyed_not_a_bare_hash(
    pg_session: AsyncSession, pg_user: AppUser
) -> None:
    """A leaked database alone must not be dictionary-attackable."""
    import hashlib

    await EncryptedDbVault(pg_session, KEY).put(pg_user.id, GARMIN_TOKENS, TOKENS)
    row = (await pg_session.execute(select(Credential))).scalar_one()

    assert row.fingerprint != hashlib.sha256(TOKENS.encode()).hexdigest()


async def test_a_rotated_key_fails_loudly(pg_session: AsyncSession, pg_user: AppUser) -> None:
    """Silently reading it as "no credential" would trigger a fresh SSO login."""
    await EncryptedDbVault(pg_session, KEY).put(pg_user.id, GARMIN_TOKENS, TOKENS)

    with pytest.raises(VaultUnavailable, match="cannot be decrypted"):
        await EncryptedDbVault(pg_session, OTHER_KEY).get(pg_user.id, GARMIN_TOKENS)


async def test_missing_credentials_are_none(pg_session: AsyncSession, pg_user: AppUser) -> None:
    assert await EncryptedDbVault(pg_session, KEY).get(pg_user.id, "garmin.nothing") is None


async def test_delete(pg_session: AsyncSession, pg_user: AppUser) -> None:
    vault = EncryptedDbVault(pg_session, KEY)
    await vault.put(pg_user.id, GARMIN_TOKENS, TOKENS)

    assert await vault.delete(pg_user.id, GARMIN_TOKENS) is True
    assert await vault.delete(pg_user.id, GARMIN_TOKENS) is False
    assert await vault.get(pg_user.id, GARMIN_TOKENS) is None


def test_a_bad_key_is_refused(pg_session: AsyncSession) -> None:
    with pytest.raises(VaultUnavailable, match="not a valid Fernet key"):
        EncryptedDbVault(pg_session, "not-a-fernet-key")


def test_build_vault_requires_a_key(pg_session: AsyncSession) -> None:
    from tests.support import local_settings

    with pytest.raises(VaultUnavailable, match="VITALS_ENCRYPTION_KEY"):
        build_vault(pg_session, local_settings(encryption_key=None))
