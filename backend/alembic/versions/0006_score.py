"""score: vitals_score, score_pillar, score_contribution

Phase 5. Three tables rather than one, because a score nobody can interrogate is a
score nobody should trust: the headline, its four pillars, and every contribution that
fed them. All of it derived from gold, so all of it rebuildable with `vitals score`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-17 21:43:25.229531
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "score_contribution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("pillar", sa.String(length=24), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("effect", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "points >= 0 and points <= 100",
            name=op.f("ck_score_contribution_points_are_out_of_100"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_score_contribution_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_contribution")),
        sa.UniqueConstraint("user_id", "calendar_date", "metric", name="uq_score_contribution_day"),
    )
    op.create_index(
        "ix_score_contribution_user_date",
        "score_contribution",
        ["user_id", "calendar_date"],
        unique=False,
    )
    op.create_table(
        "score_pillar",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("pillar", sa.String(length=24), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "score >= 0 and score <= 100", name=op.f("ck_score_pillar_score_is_out_of_100")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_score_pillar_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_pillar")),
        sa.UniqueConstraint("user_id", "calendar_date", "pillar", name="uq_score_pillar_day"),
    )
    op.create_index(
        "ix_score_pillar_user_date", "score_pillar", ["user_id", "calendar_date"], unique=False
    )
    op.create_table(
        "vitals_score",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "coverage >= 0 and coverage <= 1", name=op.f("ck_vitals_score_coverage_is_a_fraction")
        ),
        sa.CheckConstraint(
            "score >= 0 and score <= 100", name=op.f("ck_vitals_score_score_is_out_of_100")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_vitals_score_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vitals_score")),
        sa.UniqueConstraint("user_id", "calendar_date", name="uq_vitals_score_day"),
    )
    op.create_index(
        "ix_vitals_score_user_date", "vitals_score", ["user_id", "calendar_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_vitals_score_user_date", table_name="vitals_score")
    op.drop_table("vitals_score")
    op.drop_index("ix_score_pillar_user_date", table_name="score_pillar")
    op.drop_table("score_pillar")
    op.drop_index("ix_score_contribution_user_date", table_name="score_contribution")
    op.drop_table("score_contribution")
