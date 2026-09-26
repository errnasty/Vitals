"""context: day_context, day_note

The only data in this app that cannot be recovered if it is lost. Every other layer
is rebuildable from bronze; nobody can re-derive last Tuesday's mood from a watch.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-26 13:12:44.901337
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "day_context",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("tag", sa.String(length=32), nullable=False),
        sa.Column("magnitude", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "magnitude is null or magnitude >= 0",
            name=op.f("ck_day_context_magnitude_is_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_day_context_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_context")),
        sa.UniqueConstraint("user_id", "calendar_date", "tag", name="uq_day_context_tag"),
    )
    op.create_index(
        "ix_day_context_user_date", "day_context", ["user_id", "calendar_date"], unique=False
    )
    op.create_table(
        "day_note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_day_note_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_note")),
        sa.UniqueConstraint("user_id", "calendar_date", name="uq_day_note_day"),
    )


def downgrade() -> None:
    op.drop_table("day_note")
    op.drop_index("ix_day_context_user_date", table_name="day_context")
    op.drop_table("day_context")
