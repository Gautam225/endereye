"""Documents can be 'processing': saved, and being read and indexed in the background.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_documents_status"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "documents", type_="check")
    op.create_check_constraint(
        op.f(NAME), "documents", "status IN ('processing', 'ready', 'failed')"
    )


def downgrade() -> None:
    op.execute("UPDATE documents SET status = 'failed' WHERE status = 'processing'")
    op.drop_constraint(op.f(NAME), "documents", type_="check")
    op.create_check_constraint(op.f(NAME), "documents", "status IN ('ready', 'failed')")
