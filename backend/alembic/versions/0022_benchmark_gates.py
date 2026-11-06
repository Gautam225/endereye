"""Release gate for benchmark accuracy.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_gates",
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("max_drop", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("min_accuracy", sa.Float(), nullable=True),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "max_drop >= 0 AND max_drop <= 1", name=op.f("ck_benchmark_gates_max_drop")
        ),
        sa.CheckConstraint(
            "min_accuracy IS NULL OR (min_accuracy >= 0 AND min_accuracy <= 1)",
            name=op.f("ck_benchmark_gates_min_accuracy"),
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["benchmark_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("space_id"),
    )


def downgrade() -> None:
    op.drop_table("benchmark_gates")
