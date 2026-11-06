import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
ReferenceSql = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]
OutcomeName = Literal["correct", "incorrect", "failed", "not_a_query", "reference_error"]


class BenchmarkItemCreate(BaseModel):
    question: Question
    expected_sql: ReferenceSql
    ordered: bool = False


class BenchmarkItemUpdate(BaseModel):
    question: Question | None = None
    expected_sql: ReferenceSql | None = None
    ordered: bool | None = None


class BenchmarkItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    expected_sql: str
    ordered: bool
    created_at: datetime
    updated_at: datetime
    last_outcome: OutcomeName | None = None  # in the most recent run that tried it


class RunStart(BaseModel):
    """Which questions to try. Leave out `item_ids` to try them all."""

    item_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    question: str
    expected_sql: str
    generated_sql: str | None
    outcome: OutcomeName
    detail: str
    attempts: int
    expected_rows: int | None
    actual_rows: int | None
    duration_ms: int


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: Literal["running", "finished", "failed"]
    total: int
    done: int
    correct: int
    incorrect: int
    failed: int
    reference_errors: int
    error: str
    started_at: datetime
    finished_at: datetime | None
    started_by_name: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def accuracy(self) -> float | None:
        """Correct answers out of the questions that could be judged (a reference that no
        longer runs cannot judge anything). None until something was judged."""
        judged = self.done - self.reference_errors
        return round(self.correct / judged, 4) if judged > 0 else None


class RunDetail(RunOut):
    results: list[ResultOut]


class AccuracyPoint(BaseModel):
    run_id: uuid.UUID
    at: datetime
    accuracy: float | None
    correct: int
    judged: int


class GateSettings(BaseModel):
    enabled: bool = False
    max_drop: float = Field(default=0.0, ge=0, le=1)  # accuracy may fall this far below baseline
    min_accuracy: float | None = Field(default=None, ge=0, le=1)


class GateBaseline(BaseModel):
    run_id: uuid.UUID


class GateStatus(GateSettings):
    baseline_run_id: uuid.UUID | None = None
    baseline_accuracy: float | None = None
    latest_run_id: uuid.UUID | None = None
    latest_accuracy: float | None = None
    # passed: fit to publish. skipped: gate off. no_run: nothing to judge yet.
    result: Literal["passed", "failed", "skipped", "no_run"]
    reasons: list[str] = []


class AccuracyReport(BaseModel):
    points: list[AccuracyPoint]  # oldest first
    gate: GateStatus


class SpaceAccuracy(BaseModel):
    space_id: uuid.UUID
    space_name: str
    latest_accuracy: float | None
    previous_accuracy: float | None
    runs: int
    gate_result: Literal["passed", "failed", "skipped", "no_run"]
