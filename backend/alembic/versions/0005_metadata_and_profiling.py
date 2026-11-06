"""space_columns, column_values, space_joins: what the AI knows about each table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "space_tables",
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
    )
    op.add_column(
        "space_tables", sa.Column("profiled_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "space_columns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("synonyms", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("share_values", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("entity_matching", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("indexed_values", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stats", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["space_tables.id"],
            name=op.f("fk_space_columns_table_id_space_tables"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_space_columns")),
        sa.UniqueConstraint("table_id", "name", name=op.f("uq_space_columns_table_id_name")),
    )
    op.create_index(op.f("ix_space_columns_table_id"), "space_columns", ["table_id"])

    op.create_table(
        "column_values",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("column_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=127), nullable=False),
        sa.ForeignKeyConstraint(
            ["column_id"],
            ["space_columns.id"],
            name=op.f("fk_column_values_column_id_space_columns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_column_values")),
        sa.UniqueConstraint("column_id", "value", name=op.f("uq_column_values_column_id_value")),
    )
    op.create_index(op.f("ix_column_values_column_id"), "column_values", ["column_id"])
    op.create_index(
        "ix_column_values_value_trgm",
        "column_values",
        ["value"],
        postgresql_using="gin",
        postgresql_ops={"value": "gin_trgm_ops"},
    )

    op.create_table(
        "space_joins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("left_table_id", sa.Uuid(), nullable=False),
        sa.Column("left_column", sa.String(length=255), nullable=False),
        sa.Column("right_table_id", sa.Uuid(), nullable=False),
        sa.Column("right_column", sa.String(length=255), nullable=False),
        sa.Column("relationship", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "relationship IN ('many_to_one', 'one_to_many', 'one_to_one')",
            name=op.f("ck_space_joins_relationship"),
        ),
        sa.CheckConstraint("source IN ('detected', 'manual')", name=op.f("ck_space_joins_source")),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_space_joins_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["left_table_id"],
            ["space_tables.id"],
            name=op.f("fk_space_joins_left_table_id_space_tables"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_table_id"],
            ["space_tables.id"],
            name=op.f("fk_space_joins_right_table_id_space_tables"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_space_joins")),
        sa.UniqueConstraint(
            "space_id",
            "left_table_id",
            "left_column",
            "right_table_id",
            "right_column",
            name=op.f("uq_space_joins_pair"),
        ),
    )
    op.create_index(op.f("ix_space_joins_space_id"), "space_joins", ["space_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_space_joins_space_id"), table_name="space_joins")
    op.drop_table("space_joins")
    op.drop_index("ix_column_values_value_trgm", table_name="column_values")
    op.drop_index(op.f("ix_column_values_column_id"), table_name="column_values")
    op.drop_table("column_values")
    op.drop_index(op.f("ix_space_columns_table_id"), table_name="space_columns")
    op.drop_table("space_columns")
    op.drop_column("space_tables", "profiled_at")
    op.drop_column("space_tables", "description")
