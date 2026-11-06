import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportFormat(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"
    BOTH = "both"


class ReportRunStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"


class Dashboard(Base):
    """A person's own board of kept answers. Private: what a tile shows is what that person may
    read, so it is never shown to anyone else."""

    __tablename__ = "dashboards"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DashboardItem(Base):
    """A kept answer: the question, the SQL, the chart, and the result as of the last refresh."""

    __tablename__ = "dashboard_items"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text)
    chart: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    columns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    rows: Mapped[list[list[Any]] | None] = mapped_column(JSONB)  # a preview, not everything
    row_count: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_error: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    """Kept answers that are run on a schedule and sent as a PDF and/or an Excel file. It runs
    as its owner, so it only ever contains what the owner may read."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="frequency"),
        CheckConstraint("format IN ('pdf', 'xlsx', 'both')", name="format"),
        CheckConstraint("hour >= 0 AND hour <= 23", name="hour"),
        CheckConstraint("minute >= 0 AND minute <= 59", name="minute"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="weekday"),
        CheckConstraint("day_of_month >= 1 AND day_of_month <= 28", name="day_of_month"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    frequency: Mapped[str] = mapped_column(String(8), default=Frequency.WEEKLY.value)
    hour: Mapped[int] = mapped_column(Integer, default=8)
    minute: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The first of `weekdays`, kept for older rows; Monday is 0
    weekday: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    weekdays: Mapped[list[int]] = mapped_column(JSONB, default=lambda: [0], server_default="[]")
    day_of_month: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    format: Mapped[str] = mapped_column(String(8), default=ReportFormat.PDF.value)
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReportItem(Base):
    """Which kept answers a report contains, in order."""

    __tablename__ = "report_items"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboard_items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ReportRun(Base):
    """One time a report was made, on schedule or by hand, with the files it produced."""

    __tablename__ = "report_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ok', 'failed')", name="status"),
        CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(8), default="schedule")
    status: Mapped[str] = mapped_column(String(8), default=ReportRunStatus.RUNNING.value)
    error: Mapped[str] = mapped_column(String(500), default="", server_default="")
    files: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    emailed_to: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
