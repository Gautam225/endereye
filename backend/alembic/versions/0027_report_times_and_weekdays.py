"""Reports can run at any minute, and on several days of the week.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("minute", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(op.f("ck_reports_minute"), "reports", "minute >= 0 AND minute <= 59")
    op.add_column(
        "reports",
        sa.Column("weekdays", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    # Every report keeps running on the day it had; `weekday` stays as the first of them.
    op.execute("UPDATE reports SET weekdays = jsonb_build_array(weekday)")


def downgrade() -> None:
    op.drop_column("reports", "weekdays")
    op.drop_constraint(op.f("ck_reports_minute"), "reports", type_="check")
    op.drop_column("reports", "minute")
