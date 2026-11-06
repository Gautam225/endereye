"""Which pages of a document were read from a picture, and which could not be read.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("ocr_pages", "unread_pages"):
        op.add_column(
            "documents",
            sa.Column(
                name, postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
            ),
        )


def downgrade() -> None:
    op.drop_column("documents", "unread_pages")
    op.drop_column("documents", "ocr_pages")
