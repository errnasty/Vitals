"""phase 8: the anchors a person's own data supports, and experiments

`response_trait` holds measured anchors — a maximum heart rate, a nightly sleep
need — each with the number of observations behind it, because a personalised
constant without a sample size is indistinguishable from a made-up one.

`experiment` holds an N-of-1: a question written down before the days happen, which
is the only way past "you drink on Fridays and sleep badly on Fridays".

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-26 14:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "response_trait",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("trait", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column(
            "fitted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "trait", name="uq_response_trait"),
    )

    op.create_table(
        "experiment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("lag", sa.Integer(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("n_with", sa.Integer(), nullable=True),
        sa.Column("n_without", sa.Integer(), nullable=True),
        sa.Column("mean_with", sa.Float(), nullable=True),
        sa.Column("mean_without", sa.Float(), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("effect", sa.Float(), nullable=True),
        sa.Column("p_value", sa.Float(), nullable=True),
        sa.Column("significant", sa.Boolean(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiment_user_status", "experiment", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_experiment_user_status", table_name="experiment")
    op.drop_table("experiment")
    op.drop_table("response_trait")
