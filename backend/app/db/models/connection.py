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


class ConnectionStatus(StrEnum):
    UNTESTED = "untested"  # saved, never tested (or changed since the last test)
    OK = "ok"  # the last test connected and the database login is read-only
    FAILED = "failed"  # the last test could not connect or log in
    UNSAFE = "unsafe"  # connected, but the login can change data or is too powerful


class DbConnection(Base):
    """A saved connection to an external database. Read-only use only.

    The password is stored encrypted (see app/core/vault.py) and is never sent to the browser.
    """

    __tablename__ = "db_connections"
    __table_args__ = (
        CheckConstraint("engine IN ('postgresql')", name="engine"),
        CheckConstraint(
            "ssl_mode IN ('disable', 'require', 'verify-ca', 'verify-full')", name="ssl_mode"
        ),
        CheckConstraint("status IN ('untested', 'ok', 'failed', 'unsafe')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    engine: Mapped[str] = mapped_column(String(16), default="postgresql")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    database: Mapped[str] = mapped_column(String(63))
    username: Mapped[str] = mapped_column(String(63))
    password_encrypted: Mapped[str] = mapped_column(Text)
    ssl_mode: Mapped[str] = mapped_column(String(16), default="verify-full")
    # Result rows go to the AI service (to write the explanation) only when this is on.
    share_results_with_ai: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(16), default="untested")
    status_detail: Mapped[str] = mapped_column(String(500), default="", server_default="")
    server_version: Mapped[str | None] = mapped_column(String(120))
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEvent(Base):
    """Who did what to a sensitive thing. Never holds a secret."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_name: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(64))  # e.g. "connection.created"
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    target_name: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
