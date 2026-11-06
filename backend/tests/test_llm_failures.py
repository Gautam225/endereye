import email.utils
from datetime import UTC, datetime
from typing import Any

import httpx2
import openai
import pytest

from app.llm.failures import (
    BAD_REQUEST,
    DATA_POLICY,
    INVALID_KEY,
    MODEL_UNAVAILABLE,
    NETWORK_ERROR,
    NO_CREDITS,
    RATE_LIMITED,
    SERVER_ERROR,
    TIMEOUT,
    classify,
    retry_after_seconds,
)

REQUEST = httpx2.Request("POST", "https://api.test/v1/chat/completions")


def status_error(
    status: int, message: str = "boom", *, body: Any = None, headers: dict[str, str] | None = None
) -> openai.APIStatusError:
    response = httpx2.Response(status, headers=headers, request=REQUEST)
    return openai.APIStatusError(
        f"Error code: {status}",
        response=response,
        body=body if body is not None else {"message": message},
    )


@pytest.mark.parametrize(
    ("status", "message", "outcome"),
    [
        (429, "Rate limit exceeded", RATE_LIMITED),
        (402, "Insufficient credits", NO_CREDITS),
        (401, "Invalid API key", INVALID_KEY),
        (403, "Forbidden", INVALID_KEY),
        (403, "Input was flagged by moderation", BAD_REQUEST),
        (404, "No endpoints found matching your data policy", DATA_POLICY),
        (404, "Model not found", MODEL_UNAVAILABLE),
        (400, "Context length exceeded", BAD_REQUEST),
        (413, "Request too large", BAD_REQUEST),
        (408, "Request timeout", TIMEOUT),
        (500, "Internal error", SERVER_ERROR),
        (503, "Overloaded", SERVER_ERROR),
    ],
)
def test_status_codes_map_to_outcomes(status: int, message: str, outcome: str) -> None:
    failure = classify(status_error(status, message))
    assert (failure.outcome, failure.http_status, failure.message) == (outcome, status, message)


def test_openrouter_upstream_detail_is_kept() -> None:
    body = {"message": "Rate limit exceeded", "metadata": {"raw": "free tier: 50 per day"}}
    assert (
        classify(status_error(429, body=body)).message
        == "Rate limit exceeded (free tier: 50 per day)"
    )


def test_rate_limit_reads_retry_after() -> None:
    assert classify(status_error(429, headers={"retry-after": "17"})).retry_after == 17


def test_timeouts_and_network_errors() -> None:
    assert classify(openai.APITimeoutError(request=REQUEST)).outcome == TIMEOUT
    assert classify(openai.APIConnectionError(request=REQUEST)).outcome == NETWORK_ERROR
    assert classify(httpx2.ReadTimeout("slow", request=REQUEST)).outcome == TIMEOUT
    assert classify(httpx2.RemoteProtocolError("cut off", request=REQUEST)).outcome == NETWORK_ERROR


def test_retry_after_formats() -> None:
    now = 1_800_000_000.0
    assert retry_after_seconds({"retry-after": "12"}, now=now) == 12
    http_date = email.utils.format_datetime(datetime.fromtimestamp(now + 60, UTC), usegmt=True)
    assert retry_after_seconds({"retry-after": http_date}, now=now) == pytest.approx(60)
    reset_ms = str(int((now + 30) * 1000))  # OpenRouter: epoch milliseconds
    assert retry_after_seconds({"x-ratelimit-reset": reset_ms}, now=now) == pytest.approx(30)
    assert retry_after_seconds({}, now=now) is None
