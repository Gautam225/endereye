"""External database connections and the audit trail.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "db_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("engine", sa.String(16), nullable=False, server_default="postgresql"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(63), nullable=False),
        sa.Column("username", sa.String(63), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("ssl_mode", sa.String(16), nullable=False, server_default="verify-full"),
        sa.Column("status", sa.String(16), nullable=False, server_default="untested"),
        sa.Column("status_detail", sa.String(500), nullable=False, server_default=""),
        sa.Column("server_version", sa.String(120)),
        sa.Column("tested_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name", name="uq_db_connections_name"),
        sa.CheckConstraint("engine IN ('postgresql')", name=op.f("ck_db_connections_engine")),
        sa.CheckConstraint(
            "ssl_mode IN ('disable', 'require', 'verify-ca', 'verify-full')",
            name=op.f("ck_db_connections_ssl_mode"),
        ),
        sa.CheckConstraint(
            "status IN ('untested', 'ok', 'failed', 'unsafe')",
            name=op.f("ck_db_connections_status"),
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("actor_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("target_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ip", sa.String(64)),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("db_connections")
