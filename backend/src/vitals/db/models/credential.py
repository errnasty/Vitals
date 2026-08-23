"""Secrets at rest, encrypted under a key the database never sees.

Garmin tokens (and optionally a password) live here rather than in environment
variables because they *change*: the library refreshes the DI token before expiry, and
a refresh thrown away is a fresh SSO login next run — which from a datacenter IP is the
fast route to a rate-limited account.

`fingerprint` is an HMAC of the plaintext keyed with the encryption key, so a sync can
tell "the token changed, persist it" from "unchanged, skip the write" without
decrypting, and a database leak alone does not turn the column into a crackable hash.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base

# Names are namespaced by source so one vault serves every connector.
GARMIN_TOKENS = "garmin.tokens"
GARMIN_PASSWORD = "garmin.password"


class Credential(Base):
    __tablename__ = "credential"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_credential_user_id_name"),)
