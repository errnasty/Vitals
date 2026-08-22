"""initial: extensions + sync_run

Phase 0. Proves the whole migration path (local -> Supabase session pooler) and lands
the one table every later phase writes to.

Revision ID: 0001
Revises:
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector backs daily_embedding / food_memory from phase 9. Enabled now so a
    # missing extension is a phase-0 problem, not a phase-9 surprise. No-op if it was
    # already enabled from the Supabase dashboard.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "sync_run",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requests_made", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status in ('running', 'success', 'partial', 'degraded', 'failed')",
            name="status_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_run"),
    )
    op.create_index(
        "ix_sync_run_user_source_started", "sync_run", ["user_id", "source", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sync_run_user_source_started", table_name="sync_run")
    op.drop_table("sync_run")
    # Extensions are deliberately left in place: dropping them would cascade away
    # unrelated objects if anything else in the database uses them.
