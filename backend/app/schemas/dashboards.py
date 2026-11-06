import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


# ── Dashboards ───────────────────────────────────────────────────────────────


class DashboardCreate(BaseModel):
    name: Name


class DashboardUpdate(BaseModel):
    name: Name


class PinRequest(BaseModel):
    """Keep an answer. The question, SQL and chart are taken from the saved message itself."""

    conversation_id: uuid.UUID
    message_id: uuid.UUID
    dashboard_id: uuid.UUID | None = None  # leave out for the person's first dashboard
    title: Title | None = None


class ItemUpdate(BaseModel):
    title: Title | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dashboard_id: uuid.UUID
    title: str
    question: str
    sql: str
    chart: dict[str, Any] | None
    position: int
    columns: list[dict[str, Any]] | None
    rows: list[list[Any]] | None
    row_count: int | None
    truncated: bool
    refreshed_at: datetime | None
    refresh_error: str
    created_at: datetime


class DashboardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    space_id: uuid.UUID
    name: str
    created_at: datetime
    items: list[ItemOut] = []


# ── Reports ──────────────────────────────────────────────────────────────────

FrequencyName = Literal["daily", "weekly", "monthly"]
FormatName = Literal["pdf", "xlsx", "both"]


def _weekdays(value: list[int]) -> list[int]:
    """Days of the week as 0 (Monday) to 6 (Sunday): each once, in order."""
    if any(not 0 <= day <= 6 for day in value):
        raise ValueError("a day of the week is 0 (Monday) to 6 (Sunday)")
    return sorted(set(value))


class ReportSchedule(BaseModel):
    frequency: FrequencyName = "weekly"
    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    weekdays: list[int] = Field(
        default_factory=lambda: [0], min_length=1, max_length=7
    )  # Monday is 0
    day_of_month: int = Field(default=1, ge=1, le=28)
    timezone: Annotated[str, StringConstraints(max_length=64)] = "UTC"

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int]) -> list[int]:
        return _weekdays(value)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                "That time zone is not known. Use a name like Europe/London."
            ) from None
        return value


class ReportCreate(ReportSchedule):
    name: Name
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    format: FormatName = "pdf"
    recipients: list[EmailStr] = Field(default_factory=list, max_length=100)
    enabled: bool = True


class ReportUpdate(BaseModel):
    name: Name | None = None
    item_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=20)
    frequency: FrequencyName | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    timezone: str | None = Field(default=None, max_length=64)
    format: FormatName | None = None
    recipients: list[EmailStr] | None = Field(default=None, max_length=100)
    enabled: bool | None = None

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int] | None) -> list[int] | None:
        return value if value is None else _weekdays(value)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        return value if value is None else ReportSchedule.known_timezone(value)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trigger: Literal["schedule", "manual"]
    status: Literal["running", "ok", "failed"]
    error: str
    files: list[str]
    emailed_to: list[str]
    started_at: datetime
    finished_at: datetime | None


class ItemRef(BaseModel):
    id: uuid.UUID
    title: str


class ReportOut(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    name: str
    item_ids: list[uuid.UUID]
    items: list[ItemRef] = []
    frequency: FrequencyName
    hour: int
    minute: int
    weekdays: list[int]
    day_of_month: int
    timezone: str
    format: FormatName
    recipients: list[str]
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run: RunOut | None = None
    created_at: datetime


class ReportOptions(BaseModel):
    email_configured: bool
    allowed_domains: list[str]
    max_recipients: int


class KeptItemSummary(BaseModel):
    """A kept answer in a list to pick from: no result rows, so a long list stays light."""

    id: uuid.UUID
    title: str
    question: str
    dashboard_name: str


class KeptItemsPage(BaseModel):
    total: int  # how many match, not how many are on this page
    items: list[KeptItemSummary]
