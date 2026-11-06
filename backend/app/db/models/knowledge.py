import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
from app.rag.constants import EMBEDDING_DIM


class KnowledgeKind(StrEnum):
    INSTRUCTION = "instruction"  # a rule for the AI to follow
    GLOSSARY = "glossary"  # a business term and what it means
    EXAMPLE_SQL = "example_sql"  # a question and the SQL that answers it
    CLARIFICATION = "clarification"  # when to ask the user a question, and what to ask


class ChunkType(StrEnum):
    TABLE = "table"  # one card per table
    COLUMN = "column"  # one card per column
    INSTRUCTION = "instruction"
    GLOSSARY = "glossary"
    EXAMPLE_SQL = "example_sql"
    CLARIFICATION = "clarification"
    EXPRESSION = "expression"
    DOCUMENT = "document"


class DocumentStatus(StrEnum):
    PROCESSING = "processing"  # saved, text not yet read and indexed
    READY = "ready"
    FAILED = "failed"


class KnowledgeItem(Base):
    """An instruction, a glossary term, or an example question with its SQL."""

    __tablename__ = "knowledge_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('instruction', 'glossary', 'example_sql', 'clarification')", name="kind"
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    # The question (example SQL), the term (glossary), or an optional short name (instruction)
    title: Mapped[str] = mapped_column(String(500), default="", server_default="")
    # The rule, the definition, or the SQL
    body: Mapped[str] = mapped_column(Text)
    # Example SQL only: an editor has verified it, so answers that use it are marked Trusted
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Example SQL only: when it is especially relevant
    note: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExpressionType(StrEnum):
    MEASURE = "measure"  # adds up many rows: revenue, win rate
    FILTER = "filter"  # a true/false condition: large orders, completed
    DIMENSION = "dimension"  # a value to group by: deal size, fiscal quarter


class SqlExpression(Base):
    """A business definition written as SQL, applied exactly as written (not guessed)."""

    __tablename__ = "sql_expressions"
    __table_args__ = (
        UniqueConstraint("space_id", "name", name="uq_sql_expressions_space_id_name"),
        CheckConstraint("type IN ('measure', 'filter', 'dimension')", name="type"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(12))
    expression: Mapped[str] = mapped_column(Text)
    table_name: Mapped[str | None] = mapped_column(String(63))  # the table it is written for
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    synonyms: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Filters only: applied to every question that uses the table, unless the user says otherwise
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Who answers for this definition: asked about changes, and shown beside it
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Goes up with every change to the definition; each one is kept in expression_versions
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExpressionVersion(Base):
    """One saved state of a definition, so a change can be read back and undone."""

    __tablename__ = "expression_versions"
    __table_args__ = (
        UniqueConstraint(
            "expression_id", "version", name="uq_expression_versions_expression_id_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    expression_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sql_expressions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(12))
    expression: Mapped[str] = mapped_column(Text)
    table_name: Mapped[str | None] = mapped_column(String(63))
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    synonyms: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpressionTest(Base):
    """A check that a definition still gives the right number: the definition is run on its table
    (optionally narrowed by a condition) and must equal `expected`, within `tolerance`."""

    __tablename__ = "expression_tests"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    expression_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sql_expressions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    where_sql: Mapped[str | None] = mapped_column(Text)
    expected: Mapped[float] = mapped_column(Float)
    tolerance: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    last_status: Mapped[str | None] = mapped_column(String(8))  # pass, fail or error
    last_value: Mapped[float | None] = mapped_column(Float)
    last_detail: Mapped[str] = mapped_column(String(300), default="", server_default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_version: Mapped[int | None] = mapped_column(Integer)  # the version it last ran against
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    """A file whose text is searchable (PDF, Word, PowerPoint, Excel, HTML, Markdown, text)."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="status"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    parser: Mapped[str] = mapped_column(String(16))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Pages (or slides) the file has, where the format has them: so an answer can cite one.
    page_count: Mapped[int | None] = mapped_column(Integer)
    # Pages whose text (or part of it) was read from a picture with OCR, so it may hold mistakes;
    # and pages that are pictures nothing could be read from.
    ocr_pages: Mapped[list[int]] = mapped_column(JSONB, default=list, server_default="[]")
    unread_pages: Mapped[list[int]] = mapped_column(JSONB, default=list, server_default="[]")
    # Set when the file was added in a chat: only that conversation can use it
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def mention(self) -> str:
        return mention_name(self.filename)


def mention_name(filename: str) -> str:
    """What to type after @ to point at a document: its file name without spaces."""
    stem = filename.rsplit(".", 1)[0]
    return re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "document"


class Chunk(Base):
    """One searchable piece of knowledge: its text, a header, metadata, and its vector."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("space_id", "source_key", "position", name="uq_chunks_source"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    # Which thing this came from: "table:<id>", "column:<id>", "item:<id>" or "doc:<id>"
    source_key: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)  # piece number within the source
    header: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    # Content type, section path, overlap, and (for example SQL) the SQL itself
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))  # unchanged chunks are not embedded again
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
