from typing import Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    status: Literal["ok", "error"]
    version: str | None = None
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    checks: dict[str, CheckResult]
