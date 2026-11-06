"""Required PostgreSQL extensions: pgvector (embeddings) and pg_trgm (fuzzy value matching).

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.exc import DBAPIError

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REQUIRED_EXTENSIONS = ("vector", "pg_trgm")


def upgrade() -> None:
    bind = op.get_bind()
    installed = set(bind.exec_driver_sql("SELECT extname FROM pg_extension").scalars())
    for name in REQUIRED_EXTENSIONS:
        if name in installed:
            continue
        try:
            bind.exec_driver_sql(f"CREATE EXTENSION {name}")
        except DBAPIError as exc:
            raise RuntimeError(
                f"PostgreSQL extension '{name}' is missing and this user cannot create it. "
                f"Connect to this database as 'postgres' and run: CREATE EXTENSION {name};"
            ) from exc


def downgrade() -> None:
    # Extensions stay on purpose: they are database-wide, and other objects may depend on them.
    pass
