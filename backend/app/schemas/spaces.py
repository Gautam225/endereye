import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

TABLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _table_name(value: str) -> str:
    value = value.strip().lower()
    if not TABLE_NAME.fullmatch(value):
        raise ValueError(
            "use lowercase letters, digits and underscores, starting with a letter "
            "(e.g. sales_2025)"
        )
    return value


def _clean_list(max_items: int, max_length: int, what: str):
    """Trim, drop blanks and repeats (ignoring case), and enforce the limits."""

    def clean(values: list[str]) -> list[str]:
        seen: dict[str, str] = {}
        for value in values:
            value = " ".join(value.split())
            if value:
                seen.setdefault(value.lower(), value)
        cleaned = list(seen.values())
        if len(cleaned) > max_items:
            raise ValueError(f"use at most {max_items} {what}")
        if any(len(value) > max_length for value in cleaned):
            raise ValueError(f"each of the {what} can be at most {max_length} characters")
        return cleaned

    return clean


Tags = Annotated[list[str], AfterValidator(_clean_list(10, 30, "tags"))]
SuggestedQuestions = Annotated[
    list[str], AfterValidator(_clean_list(8, 200, "suggested questions"))
]
SpaceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
TableName = Annotated[str, AfterValidator(_table_name)]
SpaceRoleName = Literal["editor", "viewer"]


class SpaceCreate(BaseModel):
    name: SpaceName
    description: Description = ""


class SpaceUpdate(BaseModel):
    name: SpaceName | None = None
    description: Description | None = None
    tags: Tags | None = None
    suggested_questions: SuggestedQuestions | None = None


class SpaceOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    is_personal: bool = False  # the space behind a general chat
    tags: list[str]
    suggested_questions: list[str]
    owner_name: str | None  # who created the space
    my_role: SpaceRoleName  # admins always act as editors
    table_count: int
    member_count: int
    created_at: datetime
    updated_at: datetime


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    role: SpaceRoleName
    is_active: bool


class MemberSet(BaseModel):
    role: SpaceRoleName


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str


class ColumnOut(BaseModel):
    name: str
    type: str


class TableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: Literal["upload", "delta_path", "external"]
    source_ref: str
    connection_id: uuid.UUID | None = None
    columns: list[ColumnOut]
    row_count: int
    size_bytes: int | None
    delta_version: int | None
    description: str
    profiled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeltaTableCreate(BaseModel):
    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    name: TableName | None = None


class DataLimits(BaseModel):
    max_upload_mb: int
    file_types: list[str]  # extensions, e.g. ".csv"
    query_max_rows: int
    query_timeout_seconds: float


class QueryRequest(BaseModel):
    sql: Annotated[str, StringConstraints(max_length=20_000)]


class QueryResultOut(BaseModel):
    columns: list[ColumnOut]
    rows: list[list[Any]]
    row_count: int
    truncated: bool  # more rows existed than were returned
    elapsed_ms: int
