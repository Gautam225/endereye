import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

MessageStatusName = Literal[
    "running", "ok", "empty", "answer", "clarify", "declined", "failed", "cancelled"
]
FeedbackFilter = Literal["up", "down", "none"]
ReviewFilter = Literal["needs_review", "open", "resolved", "dismissed"]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class DayPoint(BaseModel):
    day: date
    questions: int
    failed: int
    thumbs_down: int


class MonitoringSummary(BaseModel):
    days: int
    questions: int
    by_status: dict[str, int]
    failure_rate: float  # failed / (questions that finished)
    avg_total_ms: int | None
    p95_total_ms: int | None
    avg_execute_ms: int | None
    thumbs_up: int
    thumbs_down: int
    needs_review: int
    by_day: list[DayPoint]


class MonitorRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    space_id: uuid.UUID
    space_name: str
    user_name: str
    question: str
    status: MessageStatusName
    error_code: str | None
    attempts: int
    total_ms: int | None
    execute_ms: int | None
    trusted: bool
    row_count: int | None
    feedback: Literal["up", "down"] | None
    feedback_comment: str | None
    review_status: Literal["open", "resolved", "dismissed"] | None


class MonitorList(BaseModel):
    total: int
    items: list[MonitorRow]


class MonitorDetail(MonitorRow):
    """One answer for review: what was asked, the SQL, and what went wrong. No result rows."""

    conversation_id: uuid.UUID
    standalone_question: str | None
    sql: str | None
    answer: str | None
    assumptions: list[str]
    error: str | None
    timings: dict[str, int]
    models: list[str]
    sources: list[dict]
    review_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    feedback_at: datetime | None


class ReviewIn(BaseModel):
    status: Literal["open", "resolved", "dismissed"]
    note: Note = ""


class CorrectionIn(BaseModel):
    """A verified correction: the question and the SQL that answers it properly."""

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    sql: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    trusted: bool = False
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class CorrectionOut(BaseModel):
    example_id: uuid.UUID
    row_count: int
    detail: MonitorDetail
