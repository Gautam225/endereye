"""Remember which identity-provider account a person signs in with (single sign-on).

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sso_subject", sa.String(length=600), nullable=True))
    op.create_unique_constraint("uq_users_sso_subject", "users", ["sso_subject"])


def downgrade() -> None:
    op.drop_constraint("uq_users_sso_subject", "users", type_="unique")
    op.drop_column("users", "sso_subject")
