from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KeyStatus(BaseModel):
    index: int
    masked: str
    state: Literal["ready", "resting", "disabled"]
    rest_seconds: int = 0
    model_rests: dict[str, int] = Field(default_factory=dict)  # model -> seconds left
    reason: str | None = None
    last_error: str | None = None
    successes: int = 0
    failures: int = 0
    last_used_at: datetime | None = None


class ModelStatus(BaseModel):
    id: str
    tiers: list[Literal["smart", "fast"]]
    check: Literal["ok", "missing", "unchecked", "error"]
    detail: str | None = None


class ProviderStatus(BaseModel):
    name: str
    role: Literal["primary", "fallback"]
    configured: bool
    max_prompt_tokens: int | None
    keys: list[KeyStatus]
    models: list[ModelStatus]


class RecentCalls(BaseModel):
    window_hours: int
    total: int
    by_outcome: dict[str, int]
    by_provider: dict[str, int]


class LLMStatusResponse(BaseModel):
    providers: list[ProviderStatus]
    recent_calls: RecentCalls | None  # None when the database is unavailable
