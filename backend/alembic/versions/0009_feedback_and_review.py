"""Feedback on answers, and the review of bad ones.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("feedback", sa.String(length=8), nullable=True))
    op.add_column("messages", sa.Column("feedback_comment", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("review_status", sa.String(length=12), nullable=True))
    op.add_column("messages", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column("messages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_messages_feedback"), "messages", "feedback IN ('up', 'down')"
    )
    op.create_check_constraint(
        op.f("ck_messages_review_status"),
        "messages",
        "review_status IN ('open', 'resolved', 'dismissed')",
    )
    op.create_foreign_key(
        op.f("fk_messages_reviewed_by_users"),
        "messages",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_messages_created_at", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_constraint(op.f("fk_messages_reviewed_by_users"), "messages", type_="foreignkey")
    op.drop_constraint(op.f("ck_messages_review_status"), "messages", type_="check")
    op.drop_constraint(op.f("ck_messages_feedback"), "messages", type_="check")
    for column in (
        "reviewed_at",
        "reviewed_by",
        "review_note",
        "review_status",
        "feedback_at",
        "feedback_comment",
        "feedback",
    ):
        op.drop_column("messages", column)
