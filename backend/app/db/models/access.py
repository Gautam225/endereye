import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleKind(StrEnum):
    HIDE_COLUMN = "hide_column"  # the column does not exist for the person
    MASK_COLUMN = "mask_column"  # the column exists, but every value reads as empty (NULL)
    ROW_FILTER = "row_filter"  # only the rows that match the condition exist for the person


class Audience(StrEnum):
    VIEWERS = "viewers"  # people who are viewers of the space
    MEMBERS = "members"  # viewers and editors of the space, but not admins
    EVERYONE = "everyone"  # everybody, admins too


class SpaceAccessRule(Base):
    """One restriction on what some people may read from a table of a space.

    It is applied where the data is read (the SQL guard and the engines), so it holds for the
    assistant, the SQL tab, previews and saved examples alike."""

    __tablename__ = "space_access_rules"
    __table_args__ = (
        CheckConstraint("kind IN ('hide_column', 'mask_column', 'row_filter')", name="kind"),
        CheckConstraint("audience IN ('viewers', 'members', 'everyone')", name="audience"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("space_tables.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    column: Mapped[str | None] = mapped_column(String(255))  # hide and mask
    expression: Mapped[str | None] = mapped_column(String(500))  # row filter: a SQL condition
    audience: Mapped[str] = mapped_column(String(16))
    # One person's rule: it applies to them whatever their role, and the audience is ignored.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
