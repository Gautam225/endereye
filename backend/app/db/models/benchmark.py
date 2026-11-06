import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"  # stopped before every question was tried (see `error`)


class Outcome(StrEnum):
    CORRECT = "correct"  # the assistant's result matches the reference result
    INCORRECT = "incorrect"  # it ran, and the result is different
    FAILED = "failed"  # the assistant's SQL could not be made to run
    NOT_A_QUERY = "not_a_query"  # the assistant asked, declined or answered without SQL
    REFERENCE_ERROR = "reference_error"  # the reference SQL itself no longer runs


class BenchmarkItem(Base):
    """A question with the SQL that is known to answer it correctly."""

    __tablename__ = "benchmark_items"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(String(1000))
    expected_sql: Mapped[str] = mapped_column(Text)
    # The order of the rows is part of the right answer (a ranking). Otherwise the same rows
    # in any order are right.
    ordered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BenchmarkRun(Base):
    """One pass over the benchmark questions, with its score."""

    __tablename__ = "benchmark_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'finished', 'failed')", name="status"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.RUNNING.value)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    incorrect: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    reference_errors: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(500), default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BenchmarkResult(Base):
    """What happened for one question in one run. The question and reference are copied in, so
    an old run still reads correctly after the item was edited or deleted."""

    __tablename__ = "benchmark_results"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('correct', 'incorrect', 'failed', 'not_a_query', 'reference_error')",
            name="outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benchmark_items.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(String(1000))
    expected_sql: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(String(500), default="", server_default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expected_rows: Mapped[int | None] = mapped_column(Integer)
    actual_rows: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class BenchmarkGate(Base):
    """A space's release gate: a change is only fit to publish when the latest benchmark run
    does not score below the accepted baseline run (by more than `max_drop`) nor below
    `min_accuracy`."""

    __tablename__ = "benchmark_gates"
    __table_args__ = (
        CheckConstraint("max_drop >= 0 AND max_drop <= 1", name="max_drop"),
        CheckConstraint(
            "min_accuracy IS NULL OR (min_accuracy >= 0 AND min_accuracy <= 1)", name="min_accuracy"
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    max_drop: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    min_accuracy: Mapped[float | None] = mapped_column(Float)
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benchmark_runs.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
