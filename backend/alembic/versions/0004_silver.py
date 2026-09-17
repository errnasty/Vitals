"""silver: metric_daily, metric_sample, sleep_session, activity

Phase 3. The source-agnostic layer everything above bronze reads from. Nothing here
holds anything that is not re-derivable: drop all four tables, run `vitals normalize`,
and they come back identical from the payloads in bronze. That is the property that
makes a normalizer bug a recompute rather than data loss.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("activity_type", sa.String(length=48), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("moving_duration_s", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("elevation_gain_m", sa.Float(), nullable=True),
        sa.Column("elevation_loss_m", sa.Float(), nullable=True),
        sa.Column("avg_speed_mps", sa.Float(), nullable=True),
        sa.Column("max_speed_mps", sa.Float(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Float(), nullable=True),
        sa.Column("avg_power", sa.Float(), nullable=True),
        sa.Column("max_power", sa.Float(), nullable=True),
        sa.Column("normalized_power", sa.Float(), nullable=True),
        sa.Column("aerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("anaerobic_training_effect", sa.Float(), nullable=True),
        sa.Column("training_load", sa.Float(), nullable=True),
        sa.Column("total_sets", sa.Integer(), nullable=True),
        sa.Column("total_reps", sa.Integer(), nullable=True),
        sa.Column("total_volume_kg", sa.Float(), nullable=True),
        sa.Column("raw_payload_id", sa.Uuid(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"],
            ["raw_payload.id"],
            name=op.f("fk_activity_raw_payload_id_raw_payload"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_activity_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity")),
        sa.UniqueConstraint("user_id", "source", "external_id", name="uq_activity_external"),
    )
    op.create_index("ix_activity_user_started", "activity", ["user_id", "started_at"], unique=False)
    op.create_table(
        "metric_daily",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("raw_payload_id", sa.Uuid(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"],
            ["raw_payload.id"],
            name=op.f("fk_metric_daily_raw_payload_id_raw_payload"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_metric_daily_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_daily")),
        sa.UniqueConstraint(
            "user_id", "metric", "calendar_date", "source", name="uq_metric_daily_point"
        ),
    )
    op.create_index(
        "ix_metric_daily_user_metric_date",
        "metric_daily",
        ["user_id", "metric", "calendar_date"],
        unique=False,
    )
    op.create_table(
        "metric_sample",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("raw_payload_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"],
            ["raw_payload.id"],
            name=op.f("fk_metric_sample_raw_payload_id_raw_payload"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_metric_sample_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_sample")),
        sa.UniqueConstraint(
            "user_id", "metric", "recorded_at", "source", name="uq_metric_sample_point"
        ),
    )
    op.create_index(
        "ix_metric_sample_user_metric_time",
        "metric_sample",
        ["user_id", "metric", "recorded_at"],
        unique=False,
    )
    op.create_table(
        "sleep_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("deep_s", sa.Integer(), nullable=True),
        sa.Column("light_s", sa.Integer(), nullable=True),
        sa.Column("rem_s", sa.Integer(), nullable=True),
        sa.Column("awake_s", sa.Integer(), nullable=True),
        sa.Column("nap_s", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("avg_hrv", sa.Float(), nullable=True),
        sa.Column("avg_spo2", sa.Float(), nullable=True),
        sa.Column("avg_respiration", sa.Float(), nullable=True),
        sa.Column("raw_payload_id", sa.Uuid(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["raw_payload_id"],
            ["raw_payload.id"],
            name=op.f("fk_sleep_session_raw_payload_id_raw_payload"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_sleep_session_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sleep_session")),
        sa.UniqueConstraint("user_id", "source", "calendar_date", name="uq_sleep_session_night"),
    )
    op.create_index(
        "ix_sleep_session_user_date", "sleep_session", ["user_id", "calendar_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_sleep_session_user_date", table_name="sleep_session")
    op.drop_table("sleep_session")
    op.drop_index("ix_metric_sample_user_metric_time", table_name="metric_sample")
    op.drop_table("metric_sample")
    op.drop_index("ix_metric_daily_user_metric_date", table_name="metric_daily")
    op.drop_table("metric_daily")
    op.drop_index("ix_activity_user_started", table_name="activity")
    op.drop_table("activity")
