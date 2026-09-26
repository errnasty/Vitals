"""recordings: the FIT file, and what it knew that the summary did not

`raw_file` is binary bronze — the watch's original recording, gzipped and kept
forever, because Garmin generated it once and would not generate it again.
`activity_detail` is what a decode reduces it to. No per-second sample reaches
Postgres: an hour's run is 3,600 rows across eight channels, and the facts worth
keeping fit in one row.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-26 14:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("entity_key", sa.String(length=64), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("stored_bytes", sa.Integer(), nullable=False),
        sa.Column("original_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source", "kind", "entity_key", name="uq_raw_file_entity"),
    )
    op.create_index("ix_raw_file_user_kind", "raw_file", ["user_id", "kind"])

    op.create_table(
        "activity_detail",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("sample_interval_s", sa.Float(), nullable=True),
        sa.Column("normalized_power", sa.Float(), nullable=True),
        sa.Column("variability_index", sa.Float(), nullable=True),
        sa.Column("decoupling_pct", sa.Float(), nullable=True),
        sa.Column("hr_drift_bpm", sa.Float(), nullable=True),
        sa.Column("ascent_m", sa.Float(), nullable=True),
        sa.Column("descent_m", sa.Float(), nullable=True),
        sa.Column("moving_time_s", sa.Float(), nullable=True),
        sa.Column("route_path", sa.Text(), nullable=True),
        sa.Column("route_points", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "activity_id", name="uq_activity_detail_activity"),
    )


def downgrade() -> None:
    op.drop_table("activity_detail")
    op.drop_index("ix_raw_file_user_kind", table_name="raw_file")
    op.drop_table("raw_file")
