"""ai: daily_brief

Phase 7. One row per day of prose, carrying its own provenance — who wrote it, whether
every number in it was checked against the digest, and the fingerprint of the digest it
was written from. That fingerprint is what makes a re-run free rather than billable.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19 13:02:11.408117
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_brief",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("digest_fingerprint", sa.String(length=32), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source in ('model', 'python')", name=op.f("ck_daily_brief_source_is_known")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_daily_brief_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_brief")),
        sa.UniqueConstraint("user_id", "calendar_date", name="uq_daily_brief_day"),
    )
    op.create_index(
        "ix_daily_brief_user_date", "daily_brief", ["user_id", "calendar_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_daily_brief_user_date", table_name="daily_brief")
    op.drop_table("daily_brief")
