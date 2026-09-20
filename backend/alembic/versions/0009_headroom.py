"""score_contribution: headroom

What each line would add to the score if it scored 100 from where it is. Stored beside
`effect` and for the same reason: the score already knows the answer, and a screen that
works it out by multiplying weights is a second place for that sum to go wrong.

Existing rows default to 0 and are corrected by the next `vitals score` — the layer is
disposable by design.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-20 09:41:33.520118
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "score_contribution",
        sa.Column("headroom", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("score_contribution", "headroom")
