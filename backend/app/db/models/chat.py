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
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MessageStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"  # SQL ran and returned rows
    EMPTY = "empty"  # SQL ran and returned no rows
    ANSWER = "answer"  # answered from documents, no SQL
    CLARIFY = "clarify"  # the assistant asked a question back
    DECLINED = "declined"  # the data can't answer it
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED_WITH_CONTEXT = (
    MessageStatus.OK,
    MessageStatus.EMPTY,
    MessageStatus.ANSWER,
    MessageStatus.CLARIFY,
    MessageStatus.DECLINED,
)


class Conversation(Base):
    """A chat thread. Only its owner can read it; context never crosses threads."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner", "space_id", "user_id", "updated_at"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="New chat", server_default="New chat")
    # Pinned chats stay at the top of the list, whatever their age.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Shared: the other members of the space can read it (not change it) and branch their own.
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """One turn: a question and everything the assistant did about it."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_turn"),
        CheckConstraint("feedback IN ('up', 'down')", name="feedback"),
        CheckConstraint("review_status IN ('open', 'resolved', 'dismissed')", name="review_status"),
        Index("ix_messages_created_at", "created_at"),
        CheckConstraint(
            "status IN ('running', 'ok', 'empty', 'answer', 'clarify', 'declined', "
            "'failed', 'cancelled')",
            name="status",
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # turn number within the conversation
    question: Mapped[str] = mapped_column(Text)
    # The question rewritten to stand alone ("and in March?" becomes a full question)
    standalone_question: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    sql: Mapped[str | None] = mapped_column(Text)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    answer: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    columns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    rows: Mapped[list[list[Any]] | None] = mapped_column(JSONB)  # a preview, not everything
    row_count: Mapped[int | None] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # The passages of documents the answer rests on, as cited in its text as [S1], [S2]:
    # [{"tag", "document_id", "title", "page", "text"}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    chart: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    suggestions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # For a question the assistant asked: the answers it offers (the person can also type one).
    options: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # quick, standard or deep (see chat/deep.py). A deep answer keeps its separate analyses here.
    mode: Mapped[str] = mapped_column(String(8), default="standard", server_default="standard")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    timings: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, server_default="{}")
    models: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Charts drawn from numbers in documents (checked against the documents)
    figures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # What the person who asked thought of the answer
    # Documents the person pointed at with @name: [{"id", "name"}]
    mentions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # The steps taken, as they were shown while the answer was written: [{"kind", "text"}]
    thoughts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    feedback: Mapped[str | None] = mapped_column(String(8))  # "up" or "down"
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # An administrator's review of a bad answer: open, resolved or dismissed
    review_status: Mapped[str | None] = mapped_column(String(12))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationShare(Base):
    """A chat shared with one person: they can read it, and branch a copy of their own."""

    __tablename__ = "conversation_shares"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When they first opened it: the inbox shows what is new.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
