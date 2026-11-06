import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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


class Relationship(StrEnum):
    MANY_TO_ONE = "many_to_one"  # many left rows match one right row
    ONE_TO_MANY = "one_to_many"
    ONE_TO_ONE = "one_to_one"


class JoinSource(StrEnum):
    DETECTED = "detected"  # found by looking at names and values; an editor should confirm
    MANUAL = "manual"
    FOREIGN_KEY = "foreign_key"  # declared in the external database itself; confirmed


class SpaceColumn(Base):
    """What the AI is told about one column: editable text, plus the latest profile."""

    __tablename__ = "space_columns"
    __table_args__ = (UniqueConstraint("table_id", "name", name="uq_space_columns_table_id_name"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("space_tables.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    synonyms: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Hidden columns are left out of what the AI sees. The data and permissions don't change.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # "Format assistance": sample and common values are shown to the AI.
    share_values: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # "Entity matching": the column's distinct values are searchable. Needs share_values.
    entity_matching: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    indexed_values: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # None until profiled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ColumnValue(Base):
    """One distinct value of an entity-matching column, searchable by fuzzy text match."""

    __tablename__ = "column_values"
    __table_args__ = (
        UniqueConstraint("column_id", "value", name="uq_column_values_column_id_value"),
        Index(
            "ix_column_values_value_trgm",
            "value",
            postgresql_using="gin",
            postgresql_ops={"value": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    column_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("space_columns.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[str] = mapped_column(String(127))


class SpaceJoin(Base):
    """How two tables of a space are joined (left.left_column = right.right_column)."""

    __tablename__ = "space_joins"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "left_table_id",
            "left_column",
            "right_table_id",
            "right_column",
            name="uq_space_joins_pair",
        ),
        CheckConstraint(
            "relationship IN ('many_to_one', 'one_to_many', 'one_to_one')", name="relationship"
        ),
        CheckConstraint("source IN ('detected', 'manual', 'foreign_key')", name="source"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    left_table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("space_tables.id", ondelete="CASCADE")
    )
    left_column: Mapped[str] = mapped_column(String(255))
    right_table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("space_tables.id", ondelete="CASCADE")
    )
    right_column: Mapped[str] = mapped_column(String(255))
    relationship: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
