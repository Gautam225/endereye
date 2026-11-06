"""Turn provider errors into a few outcomes that decide what happens to a key."""

import email.utils
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx2
import openai

RATE_LIMITED = "rate_limited"
INVALID_KEY = "invalid_key"
NO_CREDITS = "no_credits"
DATA_POLICY = "data_policy"
BAD_REQUEST = "bad_request"
MODEL_UNAVAILABLE = "model_unavailable"
SERVER_ERROR = "server_error"
TIMEOUT = "timeout"
NETWORK_ERROR = "network_error"

# The request or the model is the problem, not the key: another key would fail the same way.
REQUEST_PROBLEMS = frozenset({BAD_REQUEST, MODEL_UNAVAILABLE})

MESSAGE_LIMIT = 300


class ProviderResponseError(Exception):
    """A successful HTTP response we cannot use (e.g. no choices). Treated as a server error."""


@dataclass(frozen=True, slots=True)
class Failure:
    outcome: str
    message: str
    http_status: int | None = None
    retry_after: float | None = None  # seconds, when the provider says

    @property
    def is_request_problem(self) -> bool:
        return self.outcome in REQUEST_PROBLEMS


def classify(exc: BaseException) -> Failure:
    # Order matters: APITimeoutError is a subclass of APIConnectionError.
    if isinstance(exc, openai.APITimeoutError):
        return Failure(TIMEOUT, "The model took too long to answer.")
    if isinstance(exc, openai.APIConnectionError):
        return Failure(NETWORK_ERROR, "Could not reach the provider.")
    if isinstance(exc, openai.APIStatusError):
        return _classify_status(exc)
    if isinstance(exc, openai.APIError):  # e.g. an error event inside a stream
        return Failure(SERVER_ERROR, _short(_message(exc)))
    if isinstance(exc, httpx2.TimeoutException):
        return Failure(TIMEOUT, "The model stopped responding.")
    if isinstance(exc, httpx2.HTTPError):
        return Failure(NETWORK_ERROR, f"Connection problem ({type(exc).__name__}).")
    if isinstance(exc, ProviderResponseError):
        return Failure(SERVER_ERROR, _short(str(exc)))
    return Failure(SERVER_ERROR, f"Unexpected error ({type(exc).__name__}).")


def _classify_status(exc: openai.APIStatusError) -> Failure:
    status = exc.status_code
    message = _short(_message(exc))
    lowered = message.lower()
    if status == 429:
        return Failure(RATE_LIMITED, message, status, retry_after_seconds(exc.response.headers))
    if status == 402:
        return Failure(NO_CREDITS, message, status)
    if status == 401:
        return Failure(INVALID_KEY, message, status)
    if status == 403:
        # OpenRouter also answers 403 when moderation flags a prompt: not a key problem.
        if "moderation" in lowered or "flagged" in lowered:
            return Failure(BAD_REQUEST, message, status)
        return Failure(INVALID_KEY, message, status)
    if status == 404:
        if "data policy" in lowered:
            return Failure(DATA_POLICY, message, status)
        return Failure(MODEL_UNAVAILABLE, message, status)
    if status == 408:
        return Failure(TIMEOUT, message, status)
    if status in (400, 413, 422):
        return Failure(BAD_REQUEST, message, status)
    return Failure(SERVER_ERROR, message, status)


def _message(exc: openai.APIError) -> str:
    body = exc.body
    if isinstance(body, Mapping):
        message = body.get("message")
        metadata = body.get("metadata")
        if isinstance(metadata, Mapping) and isinstance(metadata.get("raw"), str):
            # OpenRouter puts the upstream provider's own error text here.
            message = f"{message} ({metadata['raw']})" if message else metadata["raw"]
        if isinstance(message, str) and message:
            return message
    return exc.message


def _short(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= MESSAGE_LIMIT else line[: MESSAGE_LIMIT - 3] + "..."


def retry_after_seconds(headers: Mapping[str, str], now: float | None = None) -> float | None:
    """Seconds to wait, from `Retry-After` or OpenRouter's `X-RateLimit-Reset` (epoch ms)."""
    now = time.time() if now is None else now
    value = headers.get("retry-after")
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - now)
            except (TypeError, ValueError):
                pass
    reset = headers.get("x-ratelimit-reset")
    if reset:
        try:
            stamp = float(reset)
        except ValueError:
            return None
        if stamp > 1e12:  # epoch milliseconds
            stamp /= 1000
        return max(0.0, stamp - now) if stamp > 1e9 else max(0.0, stamp)
    return None
