"""Tables from external database connections, and joins taken from their foreign keys.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Migration 0012 first created these three names with the naming convention applied twice.
    # Fix them on databases that already ran it (0012 is now written correctly for new ones).
    for column in ("engine", "ssl_mode", "status"):
        wrong = f"ck_db_connections_ck_db_connections_{column}"
        right = f"ck_db_connections_{column}"
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{wrong}') THEN ALTER TABLE db_connections "
            f"RENAME CONSTRAINT {wrong} TO {right}; END IF; END $$"
        )

    op.add_column(
        "space_tables",
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("db_connections.id", ondelete="RESTRICT"),
        ),
    )
    op.create_index("ix_space_tables_connection_id", "space_tables", ["connection_id"])
    op.drop_constraint(op.f("ck_space_tables_source_type"), "space_tables", type_="check")
    op.create_check_constraint(
        op.f("ck_space_tables_source_type"),
        "space_tables",
        "source_type IN ('upload', 'delta_path', 'external')",
    )
    # An external table always names its connection; a file table never does.
    op.create_check_constraint(
        op.f("ck_space_tables_connection"),
        "space_tables",
        "(source_type = 'external') = (connection_id IS NOT NULL)",
    )
    op.drop_constraint(op.f("ck_space_joins_source"), "space_joins", type_="check")
    op.create_check_constraint(
        op.f("ck_space_joins_source"),
        "space_joins",
        "source IN ('detected', 'manual', 'foreign_key')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM space_joins WHERE source = 'foreign_key'")
    op.execute("DELETE FROM space_tables WHERE source_type = 'external'")
    op.drop_constraint(op.f("ck_space_joins_source"), "space_joins", type_="check")
    op.create_check_constraint(
        op.f("ck_space_joins_source"), "space_joins", "source IN ('detected', 'manual')"
    )
    op.drop_constraint(op.f("ck_space_tables_connection"), "space_tables", type_="check")
    op.drop_constraint(op.f("ck_space_tables_source_type"), "space_tables", type_="check")
    op.create_check_constraint(
        op.f("ck_space_tables_source_type"),
        "space_tables",
        "source_type IN ('upload', 'delta_path')",
    )
    op.drop_index("ix_space_tables_connection_id", table_name="space_tables")
    op.drop_column("space_tables", "connection_id")
