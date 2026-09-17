"""initial: extensions + sync_run

Phase 0. Proves the whole migration path (local -> the deployed Postgres) and lands
the one table every later phase writes to.

Revision ID: 0001
Revises:
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_if_available(name: str) -> None:
    """Enable an extension, but only if this server's image actually ships it.

    Railway's official Postgres image carries no pgvector, and an unconditional
    CREATE EXTENSION here would fail the pre-deploy migration — blocking every deploy
    over a feature phase 9 has not reached yet. Nothing before then reads a vector, so
    absence is surfaced by `/healthz` and `vitals doctor` instead of being fatal.
    Setting VITALS_REQUIRE_PGVECTOR turns it back into a hard failure once it matters.
    """
    if context.is_offline_mode():
        # No connection to interrogate; emit the statement and let the operator decide.
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {name}")
        return

    query = sa.text("select 1 from pg_available_extensions where name = :name")
    available = op.get_bind().execute(query, {"name": name}).scalar()
    if available:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {name}")


def upgrade() -> None:
    # pgvector backs daily_embedding / food_memory from phase 9; pgcrypto is contrib
    # and present on every image we target.
    _enable_if_available("vector")
    _enable_if_available("pgcrypto")

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
