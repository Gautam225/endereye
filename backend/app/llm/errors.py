"""Errors the rest of the app sees from the gateway. Messages are shown to users."""

import math

from app.core.errors import AppError


class LLMError(AppError):
    status_code = 503
    code = "llm_error"


class LLMNotConfiguredError(LLMError):
    code = "llm_not_configured"

    def __init__(self) -> None:
        super().__init__(
            "No AI keys are configured. Add OPENROUTER_API_KEY_1 or GROQ_API_KEY_1 to .env "
            "and restart the backend."
        )


class LLMUnavailableError(LLMError):
    """Every usable key failed or is resting. `retry_after` is in whole seconds."""

    code = "llm_unavailable"

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        self.retry_after = None if not retry_after else max(1, math.ceil(retry_after))
        super().__init__(
            message,
            details={"retry_after": self.retry_after} if self.retry_after else None,
            headers={"Retry-After": str(self.retry_after)} if self.retry_after else None,
        )


class LLMRejectedError(LLMError):
    """Every model refused the request itself (too long, unsupported, flagged)."""

    status_code = 502
    code = "llm_rejected"


class LLMInvalidOutputError(LLMError):
    status_code = 502
    code = "llm_invalid_output"


class LLMStreamInterruptedError(LLMError):
    status_code = 502
    code = "llm_stream_interrupted"
