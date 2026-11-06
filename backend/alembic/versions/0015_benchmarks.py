"""Benchmark questions with reference SQL, and the runs that score the assistant against them.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE")),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("expected_sql", sa.Text(), nullable=False),
        sa.Column("ordered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_benchmark_items_space_id", "benchmark_items", ["space_id"])

    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE")),
        sa.Column("started_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("incorrect", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reference_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running', 'finished', 'failed')", name=op.f("ck_benchmark_runs_status")
        ),
    )
    op.create_index("ix_benchmark_runs_space_id", "benchmark_runs", ["space_id"])

    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("benchmark_runs.id", ondelete="CASCADE")),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("benchmark_items.id", ondelete="SET NULL")),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("expected_sql", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text()),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(500), nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_rows", sa.Integer()),
        sa.Column("actual_rows", sa.Integer()),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "outcome IN ('correct', 'incorrect', 'failed', 'not_a_query', 'reference_error')",
            name=op.f("ck_benchmark_results_outcome"),
        ),
    )
    op.create_index("ix_benchmark_results_run_id", "benchmark_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_results_run_id", table_name="benchmark_results")
    op.drop_table("benchmark_results")
    op.drop_index("ix_benchmark_runs_space_id", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
    op.drop_index("ix_benchmark_items_space_id", table_name="benchmark_items")
    op.drop_table("benchmark_items")
