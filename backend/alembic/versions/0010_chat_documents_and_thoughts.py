"""Personal (general chat) spaces, documents that belong to one conversation, mentions, and the
thought steps shown while an answer is written.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column("is_personal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    for table in ("documents", "chunks"):
        op.add_column(table, sa.Column("conversation_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_conversation_id_conversations"),
            table,
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(op.f(f"ix_{table}_conversation_id"), table, ["conversation_id"])

    op.add_column(
        "messages", sa.Column("mentions", postgresql.JSONB(), server_default="[]", nullable=False)
    )
    op.add_column(
        "messages", sa.Column("thoughts", postgresql.JSONB(), server_default="[]", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("messages", "thoughts")
    op.drop_column("messages", "mentions")
    for table in ("chunks", "documents"):
        op.drop_index(op.f(f"ix_{table}_conversation_id"), table_name=table)
        op.drop_constraint(
            op.f(f"fk_{table}_conversation_id_conversations"), table, type_="foreignkey"
        )
        op.drop_column(table, "conversation_id")
    op.drop_column("spaces", "is_personal")
