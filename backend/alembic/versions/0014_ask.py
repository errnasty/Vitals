"""phase 9: whether the journal may be shown to a model

One column, and the reason it exists is the point. The Log screen promised, on the
screen where the text was typed, that a day's note is "never analysed and never shown
to a model". Phase 9 wants to show it to one. Rather than withdraw that promise
quietly, the note reaches a model only with permission — and the default preserves
exactly what was promised.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-27 03:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "share_notes_with_ai",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_user", "share_notes_with_ai")
