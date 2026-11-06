"""Charts the assistant draws from numbers it found in documents.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("figures", postgresql.JSONB(), server_default="[]", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("messages", "figures")
