"""app_user + sync_run ownership

Phase 1. The local mirror of a Supabase identity, created on first authenticated
request. `sync_run.user_id` finally points somewhere.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        # The Supabase `sub` claim, verbatim — not a foreign key into auth.users, so
        # the schema survives a change of identity provider.
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )
    op.create_foreign_key(
        "fk_sync_run_user_id_app_user",
        "sync_run",
        "app_user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sync_run_user_id_app_user", "sync_run", type_="foreignkey")
    op.drop_table("app_user")
