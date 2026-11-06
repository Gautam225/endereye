"""Per-person restrictions on the tables of a space: hidden and masked columns, row filters.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "space_access_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE")),
        sa.Column("table_id", sa.Uuid(), sa.ForeignKey("space_tables.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("column", sa.String(255)),
        sa.Column("expression", sa.String(500)),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('hide_column', 'mask_column', 'row_filter')",
            name=op.f("ck_space_access_rules_kind"),
        ),
        sa.CheckConstraint(
            "audience IN ('viewers', 'members', 'everyone')",
            name=op.f("ck_space_access_rules_audience"),
        ),
    )
    op.create_index("ix_space_access_rules_space_id", "space_access_rules", ["space_id"])


def downgrade() -> None:
    op.drop_index("ix_space_access_rules_space_id", table_name="space_access_rules")
    op.drop_table("space_access_rules")
