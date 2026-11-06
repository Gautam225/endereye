import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Status = Literal["running", "ok", "empty", "answer", "clarify", "declined", "failed", "cancelled"]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    question: str
    standalone_question: str | None
    status: Status
    sql: str | None
    trusted: bool
    answer: str | None
    assumptions: list[str]
    columns: list[dict[str, Any]] | None
    rows: list[list[Any]] | None  # a preview; the CSV download has the whole result
    row_count: int | None
    truncated: bool
    sources: list[dict[str, Any]]
    citations: list[dict[str, Any]] = []
    chart: dict[str, Any] | None
    suggestions: list[str]
    options: list[str]
    mode: str = "standard"
    steps: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]]
    thoughts: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    feedback: Literal["up", "down"] | None
    feedback_comment: str | None
    error_code: str | None
    error: str | None
    attempts: int
    timings: dict[str, int]
    models: list[str]
    created_at: datetime
    finished_at: datetime | None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    pinned: bool = False
    shared: bool = False
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    mine: bool = True  # false for a chat someone shared: it can be read and branched, not changed
    owner_name: str | None = None


class SharedConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    owner_name: str
    updated_at: datetime


class ForkRequest(BaseModel):
    """Branch a chat: copy it up to and including this answer (or all of it) into a new chat."""

    message_id: uuid.UUID | None = None


class ConversationCreate(BaseModel):
    title: Title | None = None


class ConversationUpdate(BaseModel):
    """Rename a chat, pin or unpin it, or both."""

    title: Title | None = None
    pinned: bool | None = None
    shared: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "ConversationUpdate":
        if self.title is None and self.pinned is None and self.shared is None:
            raise ValueError("Give a new title, or say whether to pin or share the chat.")
        return self


class MessageCreate(BaseModel):
    question: Question
    # Edit an earlier question: that message and everything after it are replaced.
    replace_message_id: uuid.UUID | None = None
    # Documents pointed at with @name; the answer then uses only those documents
    mentions: Annotated[list[uuid.UUID], Field(max_length=10)] = []
    # quick: fewer AI calls, answer written here; deep: a hard question split into several analyses
    mode: Literal["quick", "standard", "deep"] = "standard"


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class ChartUpdate(BaseModel):
    """A chart as edited by a person. Checked against the result's columns."""

    type: Literal["bar", "line", "area", "pie", "scatter", "kpi"]
    x: str | None = None
    y: Annotated[list[str], Field(min_length=1, max_length=4)]
    series: str | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class DiscoverHit(BaseModel):
    """Something in the space that matches a search: a table, column, term, document, example."""

    type: Literal["table", "column", "glossary", "document", "example_sql"]
    title: str
    snippet: str
