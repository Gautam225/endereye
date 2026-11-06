import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.metadata import Synonyms

Kind = Literal["instruction", "glossary", "example_sql", "clarification"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
ChangeNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
ExpressionTestName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
Condition = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


def _check(kind: str, title: str, body: str, trusted: bool, note: str) -> None:
    if not body:
        raise ValueError(
            {
                "instruction": "write the instruction",
                "glossary": "write what the term means",
                "example_sql": "write the SQL",
                "clarification": "write what to ask",
            }[kind]
        )
    if kind in {"glossary", "example_sql", "clarification"} and not title:
        raise ValueError(
            {
                "glossary": "write the term",
                "example_sql": "write the question",
                "clarification": "write when to ask",
            }[kind]
        )
    if kind != "example_sql" and (trusted or note):
        raise ValueError("only example SQL can be trusted or have usage guidance")


class KnowledgeCreate(BaseModel):
    kind: Kind
    title: Title = ""
    body: Body
    trusted: bool = False
    note: Note = ""

    @model_validator(mode="after")
    def valid(self) -> Self:
        _check(self.kind, self.title, self.body, self.trusted, self.note)
        return self


class KnowledgeUpdate(BaseModel):
    title: Title | None = None
    body: Body | None = None
    trusted: bool | None = None
    note: Note | None = None


class KnowledgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: Kind
    title: str
    body: str
    trusted: bool
    note: str
    created_at: datetime
    updated_at: datetime


ExpressionType = Literal["measure", "filter", "dimension"]
ExpressionName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ExpressionSql = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
Described = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ExpressionCreate(BaseModel):
    name: ExpressionName
    type: ExpressionType
    expression: ExpressionSql
    table_name: str | None = None
    description: Described = ""
    synonyms: Synonyms = []
    is_default: bool = False

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.is_default and self.type != "filter":
            raise ValueError("only a filter can be applied by default")
        return self


class ExpressionUpdate(BaseModel):
    name: ExpressionName | None = None
    type: ExpressionType | None = None
    expression: ExpressionSql | None = None
    table_name: str | None = None
    description: Described | None = None
    synonyms: Synonyms | None = None
    is_default: bool | None = None
    owner_id: uuid.UUID | None = None  # hand the definition to someone else
    note: ChangeNote | None = None  # why it changed, kept with the new version
    # A change whose tests fail is refused, unless the person says to save it anyway.
    accept_failing_tests: bool = False


class ExpressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: ExpressionType
    expression: str
    table_name: str | None
    description: str
    synonyms: list[str]
    is_default: bool
    owner_id: uuid.UUID | None = None
    owner_name: str | None = None
    version: int = 1
    tests_total: int = 0
    tests_failing: int = 0  # failed or could not run at their last check
    created_at: datetime
    updated_at: datetime


class ExpressionVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    name: str
    type: ExpressionType
    expression: str
    table_name: str | None
    description: str
    synonyms: list[str]
    is_default: bool
    note: str
    changed_by_name: str | None = None
    changed_at: datetime


class RestoreRequest(BaseModel):
    accept_failing_tests: bool = False


class ExpressionTestCreate(BaseModel):
    name: ExpressionTestName
    where_sql: Condition | None = None
    expected: float
    tolerance: float = Field(default=0.0, ge=0)


class ExpressionTestUpdate(BaseModel):
    name: ExpressionTestName | None = None
    where_sql: Condition | None = None
    expected: float | None = None
    tolerance: float | None = Field(default=None, ge=0)


class ExpressionTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    expression_id: uuid.UUID
    name: str
    where_sql: str | None
    expected: float
    tolerance: float
    last_status: Literal["pass", "fail", "error"] | None
    last_value: float | None
    last_detail: str
    last_checked_at: datetime | None
    last_version: int | None


class TestRunOut(BaseModel):
    __test__ = False  # not a pytest class

    passed: int
    failed: int  # failed or could not run
    tests: list[ExpressionTestOut]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    title: str
    mention: str  # what to type after @ to point at it
    conversation_id: uuid.UUID | None
    size_bytes: int
    status: Literal["processing", "ready", "failed"]
    error: str | None
    chunk_count: int
    page_count: int | None = None
    ocr_pages: list[int] = []  # pages read from a picture: they may hold mistakes
    unread_pages: list[int] = []  # pages that are pictures nothing could be read from
    parser: str
    created_at: datetime
    uploaded_by: str | None = None  # their name, filled in by the list


class DocumentRename(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class DocumentLimits(BaseModel):
    file_types: list[str]
    max_upload_mb: int


class SearchHit(BaseModel):
    """One candidate and where it ranked at each stage."""

    id: int
    source_type: str
    header: str
    snippet: str
    vector_rank: int | None
    vector_distance: float | None
    bm25_rank: int | None
    bm25_score: float | None
    fused_rank: int | None
    rerank_score: float | None
    final_rank: int | None  # set when it was kept for the AI


class PassageOut(BaseModel):
    header: str
    text: str
    source_type: str
    score: float
    chunk_ids: list[int]
    meta: dict[str, Any]


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHit]
    passages: list[PassageOut]
    timings_ms: dict[str, int]


class IndexStatus(BaseModel):
    chunks: dict[str, int]  # by type: table, column, instruction, ...
    documents: int
    failed_documents: int
    embedding_model: str
    rerank_model: str
    chunk_tokens: int
    chunk_overlap_tokens: int
    document_parser: str


class RebuildOut(BaseModel):
    added: int
    updated: int
    removed: int
