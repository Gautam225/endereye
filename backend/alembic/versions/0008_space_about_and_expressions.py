"""About fields on spaces, clarification rules, and SQL expressions.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "spaces", sa.Column("tags", postgresql.JSONB(), server_default="[]", nullable=False)
    )
    op.add_column(
        "spaces",
        sa.Column("suggested_questions", postgresql.JSONB(), server_default="[]", nullable=False),
    )

    op.drop_constraint(op.f("ck_knowledge_items_kind"), "knowledge_items", type_="check")
    op.create_check_constraint(
        op.f("ck_knowledge_items_kind"),
        "knowledge_items",
        "kind IN ('instruction', 'glossary', 'example_sql', 'clarification')",
    )

    op.create_table(
        "sql_expressions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("type", sa.String(length=12), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("table_name", sa.String(length=63), nullable=True),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("synonyms", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "type IN ('measure', 'filter', 'dimension')", name=op.f("ck_sql_expressions_type")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_sql_expressions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_sql_expressions_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sql_expressions")),
        sa.UniqueConstraint("space_id", "name", name=op.f("uq_sql_expressions_space_id_name")),
    )
    op.create_index(op.f("ix_sql_expressions_space_id"), "sql_expressions", ["space_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sql_expressions_space_id"), table_name="sql_expressions")
    op.drop_table("sql_expressions")
    op.execute("DELETE FROM knowledge_items WHERE kind = 'clarification'")
    op.drop_constraint(op.f("ck_knowledge_items_kind"), "knowledge_items", type_="check")
    op.create_check_constraint(
        op.f("ck_knowledge_items_kind"),
        "knowledge_items",
        "kind IN ('instruction', 'glossary', 'example_sql')",
    )
    op.drop_column("spaces", "suggested_questions")
    op.drop_column("spaces", "tags")
