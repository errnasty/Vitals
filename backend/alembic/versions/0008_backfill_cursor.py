"""source_connection: backfill cursor

A history pull is a few hundred rate-governed requests — longer than a request should
live and longer than a sleeping container stays awake. These four columns turn it from
an operation into a cursor, so whoever runs next resumes where the last one stopped.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-20 09:14:02.771905
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_connection", sa.Column("backfill_from", sa.Date(), nullable=True))
    op.add_column("source_connection", sa.Column("backfill_cursor", sa.Date(), nullable=True))
    op.add_column(
        "source_connection",
        sa.Column("backfill_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_connection",
        sa.Column("backfill_finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_connection", "backfill_finished_at")
    op.drop_column("source_connection", "backfill_started_at")
    op.drop_column("source_connection", "backfill_cursor")
    op.drop_column("source_connection", "backfill_from")
