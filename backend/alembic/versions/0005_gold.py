"""gold: derived_daily

Phase 4. Everything here is derived from silver, which is itself derived from bronze,
so this table is twice removed from anything irreplaceable: drop it, run
`vitals recompute`, and it comes back. The `coverage` column is what stops a number
computed from a fortnight of history being read as one computed from six weeks.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-17 11:13:21.389546
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "derived_daily",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("inputs", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "coverage >= 0 and coverage <= 1", name=op.f("ck_derived_daily_coverage_is_a_fraction")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_derived_daily_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_derived_daily")),
        sa.UniqueConstraint("user_id", "metric", "calendar_date", name="uq_derived_daily_point"),
    )
    op.create_index(
        "ix_derived_daily_user_metric_date",
        "derived_daily",
        ["user_id", "metric", "calendar_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_derived_daily_user_metric_date", table_name="derived_daily")
    op.drop_table("derived_daily")
