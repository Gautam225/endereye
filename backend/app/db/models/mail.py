import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MailSettings(Base):
    """The mail account the app sends reports and alerts from, set up by an administrator in the
    app. There is at most one row. It takes precedence over the SMTP_* values in .env."""

    __tablename__ = "mail_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("security IN ('starttls', 'ssl', 'none')", name="security"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=587)
    security: Mapped[str] = mapped_column(String(8), default="starttls")
    username: Mapped[str] = mapped_column(String(320), default="", server_default="")
    # Encrypted with the vault (CONNECTION_ENCRYPTION_KEY); never returned by the API.
    password_encrypted: Mapped[str | None] = mapped_column(String(2000))
    from_address: Mapped[str] = mapped_column(String(320))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SavedRecipient(Base):
    """An address a person keeps to pick from when sending a report or alert."""

    __tablename__ = "saved_recipients"
    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_saved_recipients_user_id_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    label: Mapped[str] = mapped_column(String(120), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
