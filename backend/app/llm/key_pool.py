"""API keys for one provider: round-robin order, rest periods, and health counters."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.llm.failures import DATA_POLICY, INVALID_KEY, NO_CREDITS, RATE_LIMITED, Failure

MAX_REST_SECONDS = 24 * 3600
NO_CREDITS_REST_SECONDS = 3600
# After a server error or timeout, let the other keys go first for a moment.
SHORT_REST_SECONDS = 10

DISABLED_REASONS = {
    INVALID_KEY: "The provider rejected this key (invalid or revoked). "
    "Replace it in .env and restart the backend.",
    DATA_POLICY: "This OpenRouter account blocks free models. Allow them at "
    "https://openrouter.ai/settings/privacy, then restart the backend.",
}


def mask_key(secret: str) -> str:
    return f"{secret[:6]}...{secret[-4:]}" if len(secret) >= 16 else "****"


@dataclass
class ApiKey:
    index: int  # the N in OPENROUTER_API_KEY_N
    secret: str = field(repr=False)
    disabled_reason: str | None = None
    rest_until: float = 0.0  # the whole key, e.g. out of credits
    model_rest_until: dict[str, float] = field(default_factory=dict)  # rate limits are per model
    rate_limit_streak: dict[str, int] = field(default_factory=dict)
    successes: int = 0
    failures: int = 0
    last_error: str | None = None
    last_used_at: datetime | None = None

    @property
    def masked(self) -> str:
        return mask_key(self.secret)


class KeyPool:
    def __init__(
        self,
        secrets: list[str],
        *,
        rate_limit_cooldown: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.keys = [ApiKey(index=i, secret=secret) for i, secret in enumerate(secrets, start=1)]
        self._cooldown = rate_limit_cooldown
        self._clock = clock
        self._next = 0

    @property
    def configured(self) -> bool:
        return bool(self.keys)

    def rotation(self) -> list[ApiKey]:
        """All keys, starting one further along on every call, so load spreads evenly."""
        if not self.keys:
            return []
        start = self._next % len(self.keys)
        self._next = start + 1
        return self.keys[start:] + self.keys[:start]

    def is_available(self, key: ApiKey, model: str) -> bool:
        now = self._clock()
        return (
            key.disabled_reason is None
            and now >= key.rest_until
            and now >= key.model_rest_until.get(model, 0.0)
        )

    def seconds_left(self, until: float) -> float:
        return max(0.0, until - self._clock())

    def seconds_until_available(self, models: list[str]) -> float | None:
        """Shortest wait until any key can serve any of `models`. None if all are disabled."""
        waits = [
            max(
                self.seconds_left(key.rest_until),
                min(self.seconds_left(key.model_rest_until.get(m, 0.0)) for m in models),
            )
            for key in self.keys
            if key.disabled_reason is None
        ]
        return min(waits) if waits else None

    def record_success(self, key: ApiKey, model: str) -> None:
        key.successes += 1
        key.rate_limit_streak.pop(model, None)
        key.last_error = None
        key.last_used_at = datetime.now(UTC)

    def record_failure(self, key: ApiKey, model: str, failure: Failure) -> None:
        key.last_used_at = datetime.now(UTC)
        if failure.is_request_problem:
            return  # the request or model was the problem, not the key

        key.failures += 1
        key.last_error = f"{failure.outcome}: {failure.message}"[:300]
        now = self._clock()
        if failure.outcome == RATE_LIMITED:
            streak = key.rate_limit_streak.get(model, 0) + 1
            key.rate_limit_streak[model] = streak
            wait = failure.retry_after
            if wait is None:
                wait = self._cooldown * 2 ** min(streak - 1, 20)
            key.model_rest_until[model] = now + min(wait, MAX_REST_SECONDS)
        elif failure.outcome in DISABLED_REASONS:
            key.disabled_reason = DISABLED_REASONS[failure.outcome]
        elif failure.outcome == NO_CREDITS:
            key.rest_until = now + NO_CREDITS_REST_SECONDS
        else:  # server error, timeout, network error
            key.model_rest_until[model] = max(
                key.model_rest_until.get(model, 0.0), now + SHORT_REST_SECONDS
            )
