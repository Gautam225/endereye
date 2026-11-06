import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
RelationshipName = Literal["many_to_one", "one_to_many", "one_to_one"]
MAX_SYNONYMS = 20
MAX_SYNONYM_LENGTH = 60


def clean_synonyms(values: list[str]) -> list[str]:
    """Trim, drop blanks and repeats (ignoring case), keep the order."""
    seen: dict[str, str] = {}
    for value in values:
        value = " ".join(value.split())
        if value:
            seen.setdefault(value.lower(), value)
    return list(seen.values())


def _check_synonyms(values: list[str]) -> list[str]:
    cleaned = clean_synonyms(values)
    if len(cleaned) > MAX_SYNONYMS:
        raise ValueError(f"use at most {MAX_SYNONYMS} synonyms")
    if any(len(value) > MAX_SYNONYM_LENGTH for value in cleaned):
        raise ValueError(f"each synonym can be at most {MAX_SYNONYM_LENGTH} characters")
    return cleaned


Synonyms = Annotated[list[str], AfterValidator(_check_synonyms)]


class TopValue(BaseModel):
    value: str
    count: int


class ColumnStats(BaseModel):
    null_count: int
    null_pct: float
    distinct_count: int | None  # None for nested types
    min: str | None
    max: str | None
    top_values: list[TopValue]
    searchable: bool  # short text with at most 1,024 distinct values


class ColumnMeta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    position: int
    description: str
    synonyms: list[str]
    hidden: bool
    share_values: bool
    entity_matching: bool
    indexed_values: int
    stats: ColumnStats | None


class TableMeta(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    row_count: int
    profiled_at: datetime | None
    stale: bool  # a Delta table has a newer version than the one profiled
    columns: list[ColumnMeta]


class TableMetaUpdate(BaseModel):
    description: Text


class ColumnMetaUpdate(BaseModel):
    description: Text | None = None
    synonyms: Synonyms | None = None
    hidden: bool | None = None
    share_values: bool | None = None
    entity_matching: bool | None = None


class ColumnDraft(BaseModel):
    name: str = Field(description="Exact column name, as given")
    description: str = Field(description="One or two plain sentences, at most 250 characters")
    synonyms: list[str] = Field(
        default_factory=list, description="Up to 5 other words a user might use for this column"
    )


class TableDraft(BaseModel):
    description: str = Field(description="What one row of the table is, in one or two sentences")
    columns: list[ColumnDraft]


class JoinOut(BaseModel):
    id: uuid.UUID
    left_table_id: uuid.UUID
    left_table: str
    left_column: str
    right_table_id: uuid.UUID
    right_table: str
    right_column: str
    relationship: RelationshipName
    source: Literal["detected", "manual", "foreign_key"]
    confirmed: bool


class JoinCreate(BaseModel):
    left_table_id: uuid.UUID
    left_column: str
    right_table_id: uuid.UUID
    right_column: str
    relationship: RelationshipName


class JoinUpdate(BaseModel):
    left_column: str | None = None
    right_column: str | None = None
    relationship: RelationshipName | None = None
    confirmed: bool | None = None


class ValueMatch(BaseModel):
    table: str
    column: str
    value: str
    score: float
