import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SpaceRole(StrEnum):
    EDITOR = "editor"  # manages the space's data and members
    VIEWER = "viewer"  # asks questions


class SourceType(StrEnum):
    UPLOAD = "upload"  # a file someone uploaded, stored as Parquet
    DELTA_PATH = "delta_path"  # a Delta table folder on this machine
    EXTERNAL = "external"  # a table or view in an external database (a saved connection)


class Space(Base):
    """A workspace around one topic: its data tables, members, and (later) knowledge."""

    __tablename__ = "spaces"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    # A person's own space for the general chat (no tables). Never listed with the others.
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # About: free labels, and questions to offer when a conversation starts
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    suggested_questions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Goes up whenever the space's searchable knowledge changes (keyword indexes are rebuilt)
    index_version: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SpaceMember(Base):
    __tablename__ = "space_members"
    __table_args__ = (CheckConstraint("role IN ('editor', 'viewer')", name="role"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpaceTable(Base):
    """One table the space can query: an uploaded file or a Delta table."""

    __tablename__ = "space_tables"
    __table_args__ = (
        UniqueConstraint("space_id", "name", name="uq_space_tables_space_id_name"),
        CheckConstraint("source_type IN ('upload', 'delta_path', 'external')", name="source_type"),
        CheckConstraint(
            "(source_type = 'external') = (connection_id IS NOT NULL)", name="connection"
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(63))  # the name used in SQL
    source_type: Mapped[str] = mapped_column(String(16))
    source_ref: Mapped[str] = mapped_column(String(1000))  # file name, or Delta folder
    storage_path: Mapped[str] = mapped_column(String(1000))  # Parquet file, Delta folder, or ""
    # For an external table: the saved connection (source_ref is "schema.table"). A connection
    # that has tables cannot be deleted.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("db_connections.id", ondelete="RESTRICT"), index=True
    )
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # [{"name", "type"}]
    row_count: Mapped[int] = mapped_column(BigInteger)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    delta_version: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    profiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
