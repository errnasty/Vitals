"""credential + source_connection + raw_payload

Phase 2. Encrypted credential storage, per-source connection state, and the immutable
bronze store every later phase derives from.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        # Keyed HMAC of the plaintext: change detection without decrypting, and not
        # dictionary-attackable from a database leak alone.
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_credential_user_id_app_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credential"),
        sa.UniqueConstraint("user_id", "name", name="uq_credential_user_id_name"),
    )

    op.create_table(
        "source_connection",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        # Persisted so a container restart cannot stampede past a rate limit the
        # previous run earned.
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status in ('active', 'degraded', 'needs_reauth', 'disabled')",
            name="status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name="fk_source_connection_user_id_app_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_connection"),
        sa.UniqueConstraint("user_id", "source", name="uq_source_connection_user_id_source"),
    )

    op.create_table(
        "raw_payload",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=True),
        sa.Column("entity_key", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sync_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_raw_payload_user_id_app_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_run.id"],
            name="fk_raw_payload_sync_run_id_sync_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_payload"),
        # NULLS NOT DISTINCT (PG15+): calendar_date and entity_key are legitimately
        # null for undated payloads, and under default NULL semantics those rows would
        # never collide, so every sync would re-insert them.
        sa.UniqueConstraint(
            "user_id",
            "source",
            "endpoint",
            "calendar_date",
            "entity_key",
            "payload_hash",
            name="uq_raw_payload_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_raw_payload_user_source_endpoint_date",
        "raw_payload",
        ["user_id", "source", "endpoint", "calendar_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_payload_user_source_endpoint_date", table_name="raw_payload")
    op.drop_table("raw_payload")
    op.drop_table("source_connection")
    op.drop_table("credential")
