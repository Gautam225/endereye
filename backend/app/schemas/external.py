import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.spaces import TableOut

NAME_CHARS = "\"'`;\\/\r\n\t\x00"


class ColumnFound(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    comment: str


class ForeignKeyFound(BaseModel):
    name: str
    columns: list[str]
    ref_schema: str
    ref_table: str
    ref_columns: list[str]
    # A join is one column to one column; a key over several columns is listed but not stored.
    supported: bool


class TableFound(BaseModel):
    schema_name: str = Field(serialization_alias="schema")
    name: str
    kind: str
    comment: str
    estimated_rows: int | None
    columns: list[ColumnFound]
    foreign_keys: list[ForeignKeyFound]
    attached_here: bool = False

    model_config = {"populate_by_name": True}


class ExternalTableRef(BaseModel):
    schema_name: str = Field(alias="schema", min_length=1, max_length=63)
    name: str = Field(min_length=1, max_length=63)
    alias: str | None = Field(default=None, max_length=63)

    model_config = {"populate_by_name": True}

    @field_validator("schema_name", "name")
    @classmethod
    def _plain(cls, value: str) -> str:
        if any(ch in value for ch in NAME_CHARS):
            raise ValueError("This contains a character that is not allowed.")
        return value


class ExternalAttach(BaseModel):
    connection_id: uuid.UUID
    tables: list[ExternalTableRef] = Field(min_length=1, max_length=50)


class ExternalAttachOut(BaseModel):
    tables: list[TableOut]
    joins_created: int
    skipped_foreign_keys: list[str]


class TypeChange(BaseModel):
    column: str
    from_type: str
    to_type: str


class TableChange(BaseModel):
    name: str
    ref: str
    status: Literal["unchanged", "changed", "missing"]
    added_columns: list[str] = []
    removed_columns: list[str] = []
    type_changes: list[TypeChange] = []


class RefreshOut(BaseModel):
    applied: bool
    tables: list[TableChange]
    joins_added: int
    joins_removed: int
    skipped_foreign_keys: list[str]
