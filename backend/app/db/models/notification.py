import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    """Something a person should hear about, shown as a pop-up in the app. It is created where
    the thing happens (a report finishes, an alert fires) and handed to the browser once."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("level IN ('info', 'success', 'warning', 'error')", name="level"),
        Index("ix_notifications_user_id_delivered_at", "user_id", "delivered_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))  # what happened: "report_ready", "alert_fired"
    level: Mapped[str] = mapped_column(String(8), default="info")
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(400), default="", server_default="")
    link: Mapped[str] = mapped_column(
        String(400), default="", server_default=""
    )  # a page of the app
    # One optional button: {"type": "download", "label": ..., "path": ..., "filename": ...}
    action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Not shown when the person is already looking at `link` (a chat answer on its own page)
    quiet_when_here: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # The same problem is announced once: another with this key within the window is dropped
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
