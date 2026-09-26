"""insights: what moves your numbers

One row per tag/metric/lag the analysis tested, with the sample and the p-value
behind it. `tested` carries the denominator: three findings out of two hundred tests
is a very different statement from three out of four.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-26 13:48:19.662104
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "insight",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("lag", sa.Integer(), nullable=False),
        sa.Column("n_with", sa.Integer(), nullable=False),
        sa.Column("n_without", sa.Integer(), nullable=False),
        sa.Column("mean_with", sa.Float(), nullable=False),
        sa.Column("mean_without", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("effect", sa.Float(), nullable=False),
        sa.Column("p_value", sa.Float(), nullable=False),
        sa.Column("significant", sa.Boolean(), nullable=False),
        sa.Column("tested", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_insight_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insight")),
        sa.UniqueConstraint("user_id", "tag", "metric", "lag", name="uq_insight_pair"),
    )
    op.create_index(
        "ix_insight_user_significant", "insight", ["user_id", "significant"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_insight_user_significant", table_name="insight")
    op.drop_table("insight")
