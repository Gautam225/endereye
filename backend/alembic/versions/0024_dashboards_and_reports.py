"""Saved dashboards (kept answers) and scheduled reports.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        _created(),
        _updated(),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboards_space_id", "dashboards", ["space_id"])
    op.create_index("ix_dashboards_owner_id", "dashboards", ["owner_id"])

    op.create_table(
        "dashboard_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("chart", postgresql.JSONB(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=True),
        sa.Column("rows", postgresql.JSONB(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_error", sa.String(500), server_default="", nullable=False),
        _created(),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboard_items_dashboard_id", "dashboard_items", ["dashboard_id"])

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("frequency", sa.String(8), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), server_default="0", nullable=False),
        sa.Column("day_of_month", sa.Integer(), server_default="1", nullable=False),
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _updated(),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly')", name=op.f("ck_reports_frequency")
        ),
        sa.CheckConstraint("format IN ('pdf', 'xlsx', 'both')", name=op.f("ck_reports_format")),
        sa.CheckConstraint("hour >= 0 AND hour <= 23", name=op.f("ck_reports_hour")),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name=op.f("ck_reports_weekday")),
        sa.CheckConstraint(
            "day_of_month >= 1 AND day_of_month <= 28", name=op.f("ck_reports_day_of_month")
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_space_id", "reports", ["space_id"])
    op.create_index("ix_reports_owner_id", "reports", ["owner_id"])
    op.create_index("ix_reports_next_run_at", "reports", ["next_run_at"])

    op.create_table(
        "report_items",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["dashboard_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id", "item_id"),
    )
    op.create_index("ix_report_items_item_id", "report_items", ["item_id"])

    op.create_table(
        "report_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error", sa.String(500), server_default="", nullable=False),
        sa.Column("files", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("emailed_to", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'ok', 'failed')", name=op.f("ck_report_runs_status")
        ),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual')", name=op.f("ck_report_runs_trigger")
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_runs_report_id", "report_runs", ["report_id"])


def downgrade() -> None:
    op.drop_table("report_runs")
    op.drop_table("report_items")
    op.drop_table("reports")
    op.drop_table("dashboard_items")
    op.drop_table("dashboards")
