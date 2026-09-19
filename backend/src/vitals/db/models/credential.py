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
# A login that has been started and is waiting for an MFA code. Holds the resumable
# state and, for the few minutes it lives, the credentials needed to rebuild the
# client — encrypted like everything else here, and deleted the moment the code is
# accepted, rejected for the last time, or the window closes.
GARMIN_PENDING_LOGIN = "garmin.pending_login"
# Failed attempt count and lockout, so a web form cannot be used to hammer Garmin's
# SSO. Separate from `source_connection.consecutive_failures`, which counts sync
# failures and must not be reset by someone retrying a password.
GARMIN_LOGIN_ATTEMPTS = "garmin.login_attempts"


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
