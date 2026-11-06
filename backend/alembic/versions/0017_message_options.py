"""The answers the assistant offers along with a question it asks.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("options", postgresql.JSONB(), server_default="[]", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("messages", "options")
