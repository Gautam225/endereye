"""How a question was answered (quick, standard or deep) and the separate analyses of a deep one.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("mode", sa.String(8), server_default="standard", nullable=False)
    )
    op.add_column(
        "messages", sa.Column("steps", postgresql.JSONB(), server_default="[]", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("messages", "steps")
    op.drop_column("messages", "mode")
