"""Shared metrics (owners, versions, tests) and alerts.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.add_column("sql_expressions", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sql_expressions",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_foreign_key(
        "fk_sql_expressions_owner_id_users",
        "sql_expressions",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sql_expressions_owner_id", "sql_expressions", ["owner_id"])
    op.execute("UPDATE sql_expressions SET owner_id = created_by")

    op.create_table(
        "expression_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expression_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("type", sa.String(12), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("table_name", sa.String(63), nullable=True),
        sa.Column("description", sa.String(1000), server_default="", nullable=False),
        sa.Column("synonyms", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("note", sa.String(300), server_default="", nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        _created("changed_at"),
        sa.ForeignKeyConstraint(["expression_id"], ["sql_expressions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "expression_id", "version", name="uq_expression_versions_expression_id_version"
        ),
    )
    op.create_index(
        "ix_expression_versions_expression_id", "expression_versions", ["expression_id"]
    )
    # Every definition that exists already becomes its own version 1.
    op.execute(
        """
        INSERT INTO expression_versions
            (id, expression_id, version, name, type, expression, table_name, description,
             synonyms, is_default, note, changed_by, changed_at)
        SELECT gen_random_uuid(), id, 1, name, type, expression, table_name, description,
               synonyms, is_default, 'Before versions were kept', created_by, created_at
        FROM sql_expressions
        """
    )

    op.create_table(
        "expression_tests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expression_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("where_sql", sa.Text(), nullable=True),
        sa.Column("expected", sa.Float(), nullable=False),
        sa.Column("tolerance", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_status", sa.String(8), nullable=True),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_detail", sa.String(300), server_default="", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_version", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(["expression_id"], ["sql_expressions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expression_tests_expression_id", "expression_tests", ["expression_id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(8), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("value_column", sa.String(120), nullable=True),
        sa.Column("expression_id", sa.Uuid(), nullable=True),
        sa.Column("where_sql", sa.String(2000), nullable=True),
        sa.Column("operator", sa.String(4), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("renotify_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column(
            "notify_on_recovery", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_error", sa.String(500), server_default="", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint("source_type IN ('item', 'metric')", name=op.f("ck_alerts_source_type")),
        sa.CheckConstraint(
            "operator IN ('gt', 'gte', 'lt', 'lte')", name=op.f("ck_alerts_operator")
        ),
        sa.CheckConstraint(
            "state IN ('new', 'ok', 'triggered', 'error')", name=op.f("ck_alerts_state")
        ),
        sa.CheckConstraint(
            "interval_minutes IN (15, 60, 360, 1440)", name=op.f("ck_alerts_interval_minutes")
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["dashboard_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["expression_id"], ["sql_expressions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_space_id", "alerts", ["space_id"])
    op.create_index("ix_alerts_owner_id", "alerts", ["owner_id"])
    op.create_index("ix_alerts_next_check_at", "alerts", ["next_check_at"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("message", sa.String(500), server_default="", nullable=False),
        sa.Column("emailed_to", postgresql.JSONB(), server_default="[]", nullable=False),
        _created("at"),
        sa.CheckConstraint(
            "kind IN ('triggered', 'recovered', 'error')", name=op.f("ck_alert_events_kind")
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_events_alert_id", "alert_events", ["alert_id"])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("expression_tests")
    op.drop_table("expression_versions")
    op.drop_index("ix_sql_expressions_owner_id", table_name="sql_expressions")
    op.drop_constraint("fk_sql_expressions_owner_id_users", "sql_expressions", type_="foreignkey")
    op.drop_column("sql_expressions", "version")
    op.drop_column("sql_expressions", "owner_id")
