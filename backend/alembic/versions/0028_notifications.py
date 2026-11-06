"""Notifications: pop-ups for things that happen while a person is in the app.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(400), server_default="", nullable=False),
        sa.Column("link", sa.String(400), server_default="", nullable=False),
        sa.Column("action", postgresql.JSONB(), nullable=True),
        sa.Column("quiet_when_here", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "level IN ('info', 'success', 'warning', 'error')", name=op.f("ck_notifications_level")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index(
        "ix_notifications_user_id_delivered_at", "notifications", ["user_id", "delivered_at"]
    )


def downgrade() -> None:
    op.drop_table("notifications")
