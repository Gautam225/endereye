"""Mail account set up in the app, and each person's saved email addresses.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mail_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("security", sa.String(8), nullable=False),
        sa.Column("username", sa.String(320), server_default="", nullable=False),
        sa.Column("password_encrypted", sa.String(2000), nullable=True),
        sa.Column("from_address", sa.String(320), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_mail_settings_single_row")),
        sa.CheckConstraint(
            "security IN ('starttls', 'ssl', 'none')", name=op.f("ck_mail_settings_security")
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "saved_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("label", sa.String(120), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "email", name="uq_saved_recipients_user_id_email"),
    )
    op.create_index("ix_saved_recipients_user_id", "saved_recipients", ["user_id"])


def downgrade() -> None:
    op.drop_table("saved_recipients")
    op.drop_table("mail_settings")
