"""A table of an external database whose size is not known is -1, not 0.

Until now an unknown size was saved as 0, so the assistant was told "0 rows" for tables that
have data and concluded they were empty. The server's size estimate is often missing (it exists
only after the table was analysed), so 0 is treated as unknown for these tables.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE space_tables SET row_count = -1 WHERE source_type = 'external' AND row_count = 0"
    )


def downgrade() -> None:
    op.execute("UPDATE space_tables SET row_count = 0 WHERE row_count < 0")
