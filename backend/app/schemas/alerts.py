import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Condition = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Column = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]

SourceName = Literal["item", "metric"]
OperatorName = Literal["gt", "gte", "lt", "lte"]
StateName = Literal["new", "ok", "triggered", "error"]
IntervalMinutes = Literal[15, 60, 360, 1440]


class AlertCreate(BaseModel):
    name: Name
    source_type: SourceName
    item_id: uuid.UUID | None = None  # a kept answer: its first number (or `value_column`)
    value_column: Column | None = None
    expression_id: uuid.UUID | None = None  # a shared metric, evaluated on its table
    where_sql: Condition | None = None  # narrows the rows a metric is worked out over
    operator: OperatorName
    threshold: float
    interval_minutes: IntervalMinutes = 60
    recipients: list[EmailStr] = Field(default_factory=list, max_length=100)
    renotify_hours: int = Field(default=24, ge=0, le=720)  # 0: tell me once per episode
    notify_on_recovery: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def has_a_source(self) -> Self:
        if self.source_type == "item" and self.item_id is None:
            raise ValueError("choose the kept answer to watch")
        if self.source_type == "metric" and self.expression_id is None:
            raise ValueError("choose the metric to watch")
        return self


class AlertUpdate(BaseModel):
    name: Name | None = None
    value_column: Column | None = None
    where_sql: Condition | None = None
    operator: OperatorName | None = None
    threshold: float | None = None
    interval_minutes: IntervalMinutes | None = None
    recipients: list[EmailStr] | None = Field(default=None, max_length=100)
    renotify_hours: int | None = Field(default=None, ge=0, le=720)
    notify_on_recovery: bool | None = None
    enabled: bool | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    space_id: uuid.UUID
    name: str
    source_type: SourceName
    item_id: uuid.UUID | None
    item_title: str | None = None
    value_column: str | None
    expression_id: uuid.UUID | None
    expression_name: str | None = None
    where_sql: str | None
    operator: OperatorName
    threshold: float
    interval_minutes: int
    recipients: list[str]
    renotify_hours: int
    notify_on_recovery: bool
    enabled: bool
    state: StateName
    last_value: float | None
    last_error: str
    last_checked_at: datetime | None
    last_triggered_at: datetime | None
    next_check_at: datetime | None
    created_at: datetime


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: Literal["triggered", "recovered", "error"]
    value: float | None
    message: str
    emailed_to: list[str]
    at: datetime
