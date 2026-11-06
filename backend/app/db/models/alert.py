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
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertSource(StrEnum):
    ITEM = "item"  # a kept answer: its first number
    METRIC = "metric"  # a shared definition, evaluated on its table


class Operator(StrEnum):
    GT = "gt"  # above
    GTE = "gte"  # at least
    LT = "lt"  # below
    LTE = "lte"  # at most


class AlertState(StrEnum):
    NEW = "new"  # never checked
    OK = "ok"  # fine at the last check
    TRIGGERED = "triggered"  # the condition holds
    ERROR = "error"  # the number could not be worked out


class Alert(Base):
    """ "Tell me when this number goes above that." Checked on a schedule as its owner, so it only
    ever reads what the owner may read."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("source_type IN ('item', 'metric')", name="source_type"),
        CheckConstraint("operator IN ('gt', 'gte', 'lt', 'lte')", name="operator"),
        CheckConstraint("state IN ('new', 'ok', 'triggered', 'error')", name="state"),
        CheckConstraint("interval_minutes IN (15, 60, 360, 1440)", name="interval_minutes"),
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
    source_type: Mapped[str] = mapped_column(String(8))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dashboard_items.id", ondelete="SET NULL")
    )
    value_column: Mapped[str | None] = mapped_column(String(120))  # item: which column; else first
    expression_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sql_expressions.id", ondelete="SET NULL")
    )
    where_sql: Mapped[str | None] = mapped_column(String(2000))  # metric: narrow the rows first
    operator: Mapped[str] = mapped_column(String(4))
    threshold: Mapped[float] = mapped_column(Float)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    renotify_hours: Mapped[int] = mapped_column(Integer, default=24, server_default="24")
    notify_on_recovery: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    state: Mapped[str] = mapped_column(String(10), default=AlertState.NEW.value)
    last_value: Mapped[float | None] = mapped_column(Float)
    last_error: Mapped[str] = mapped_column(String(500), default="", server_default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertEvent(Base):
    """What an alert did: went off, recovered, or could not be checked."""

    __tablename__ = "alert_events"
    __table_args__ = (CheckConstraint("kind IN ('triggered', 'recovered', 'error')", name="kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String(500), default="", server_default="")
    emailed_to: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
