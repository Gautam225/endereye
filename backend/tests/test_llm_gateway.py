"""Gateway behaviour against a fake OpenRouter + Groq (no network, no real keys)."""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from app.core.config import load_settings
from app.llm.errors import (
    LLMInvalidOutputError,
    LLMNotConfiguredError,
    LLMRejectedError,
    LLMStreamInterruptedError,
    LLMUnavailableError,
)
from app.llm.gateway import LLMGateway
from app.llm.types import CallRecord, StreamDelta, StreamEnd, StreamStart, StreamThinking, Usage

pytestmark = pytest.mark.anyio

OR_KEYS = [f"sk-or-test-key-{n}-0000000000" for n in range(1, 5)]
GROQ_KEYS = [f"gsk_test_key_{n}_0000000000" for n in range(1, 5)]
MSG = [{"role": "user", "content": "How many orders last week?"}]

Call = dict[str, Any]


class FakeAPI:
    """Stands in for both providers. Records every request; `respond` decides the answer."""

    def __init__(self, respond: Callable[[Call], httpx2.Response]) -> None:
        self.respond = respond
        self.requests: list[Call] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else {}
        match = re.search(r"key[-_](\d+)", request.headers.get("authorization", ""))
        call = {
            "provider": "groq" if request.url.host == "groq.test" else "openrouter",
            "key": int(match.group(1)) if match else None,
            "model": body.get("model"),
            "path": request.url.path,
            "body": body,
        }
        self.requests.append(call)
        return self.respond(call)


def make_gateway(
    fake: FakeAPI,
    *,
    or_keys: list[str] = OR_KEYS,
    groq_keys: list[str] = GROQ_KEYS,
    records: list[CallRecord] | None = None,
    **overrides: Any,
) -> LLMGateway:
    settings = load_settings(
        _env_file=None,
        postgres_password="unused",
        secret_key="test-secret-" + "x" * 32,
        openrouter_api_keys=or_keys,
        groq_api_keys=groq_keys,
        openrouter_base_url="https://openrouter.test/api/v1",
        groq_base_url="https://groq.test/openai/v1",
        openrouter_models_smart=["or/smart-a", "or/smart-b"],
        openrouter_models_fast=["or/fast"],
        groq_models_smart=["groq/smart"],
        groq_models_fast=["groq/fast"],
        **overrides,
    )
    return LLMGateway.from_settings(
        settings,
        recorder=records.append if records is not None else None,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fake)),
    )


def ok(text: str | None = "Hello", *, tool_args: dict[str, Any] | None = None) -> httpx2.Response:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_args is not None:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "submit", "arguments": json.dumps(tool_args)},
                }
            ],
        }
    return httpx2.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        },
    )


def fail(
    status: int, message: str = "nope", headers: dict[str, str] | None = None
) -> httpx2.Response:
    return httpx2.Response(
        status, json={"error": {"message": message, "code": status}}, headers=headers
    )


def chunk(
    content: str | None = None,
    *,
    reasoning: str | None = None,
    finish: str | None = None,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning"] = reasoning
    data: dict[str, Any] = {
        "id": "s1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        data["usage"] = usage
    return data


def sse(*chunks: dict[str, Any]) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=body.encode()
    )


# ── Key rotation and fallback ────────────────────────────────────────────────


async def test_rate_limited_key_rests_and_the_next_key_answers() -> None:
    fake = FakeAPI(
        lambda c: fail(429, "slow down", {"retry-after": "30"}) if c["key"] == 1 else ok()
    )
    records: list[CallRecord] = []
    gateway = make_gateway(fake, records=records)

    result = await gateway.complete(MSG, purpose="test")

    assert (result.provider, result.key_index, result.text) == ("openrouter", 2, "Hello")
    pool, key1 = gateway.providers[0].pool, gateway.providers[0].pool.keys[0]
    assert not pool.is_available(key1, "or/fast")  # rate limits are per model...
    assert pool.is_available(key1, "or/smart-a")  # ...so key 1 still serves other models
    assert [(r.key_index, r.outcome) for r in records] == [(1, "rate_limited"), (2, "ok")]
    assert records[1].prompt_tokens == 12


async def test_requests_rotate_through_the_keys() -> None:
    fake = FakeAPI(lambda c: ok())
    gateway = make_gateway(fake)
    for _ in range(5):
        await gateway.complete(MSG, purpose="test")
    assert [c["key"] for c in fake.requests] == [1, 2, 3, 4, 1]


async def test_falls_back_to_groq_when_every_openrouter_key_is_invalid() -> None:
    fake = FakeAPI(lambda c: fail(401, "bad key") if c["provider"] == "openrouter" else ok())
    gateway = make_gateway(fake)

    result = await gateway.complete(MSG, purpose="test")

    assert (result.provider, result.model, result.key_index) == ("groq", "groq/fast", 1)
    assert all(key.disabled_reason for key in gateway.providers[0].pool.keys)

    fake.requests.clear()
    await gateway.complete(MSG, purpose="test")
    assert {c["provider"] for c in fake.requests} == {"groq"}  # disabled keys are skipped


async def test_bad_request_moves_to_the_next_model_without_trying_other_keys() -> None:
    fake = FakeAPI(lambda c: fail(400, "context too long") if c["model"] == "or/smart-a" else ok())
    gateway = make_gateway(fake)

    result = await gateway.complete(MSG, purpose="test", tier="smart")

    assert result.model == "or/smart-b"
    assert [(c["model"], c["key"]) for c in fake.requests] == [("or/smart-a", 1), ("or/smart-b", 1)]
    assert gateway.providers[0].pool.keys[0].failures == 0  # not the key's fault


async def test_data_policy_error_disables_the_key_with_fix_instructions() -> None:
    blocked = "No endpoints found matching your data policy (Free model publication)"
    fake = FakeAPI(
        lambda c: fail(404, blocked) if c["provider"] == "openrouter" and c["key"] == 1 else ok()
    )
    gateway = make_gateway(fake)

    result = await gateway.complete(MSG, purpose="test")

    assert result.key_index == 2
    reason = gateway.providers[0].pool.keys[0].disabled_reason
    assert reason is not None
    assert "openrouter.ai/settings/privacy" in reason


async def test_busy_everywhere_raises_unavailable_with_retry_after() -> None:
    fake = FakeAPI(lambda c: fail(429, "limit", {"retry-after": "120"}))
    gateway = make_gateway(fake)

    with pytest.raises(LLMUnavailableError) as caught:
        await gateway.complete(MSG, purpose="test")

    assert caught.value.retry_after == 120
    assert caught.value.headers == {"Retry-After": "120"}
    assert len(fake.requests) == 8  # each of the 4 + 4 keys tried exactly once

    fake.requests.clear()
    with pytest.raises(LLMUnavailableError):
        await gateway.complete(MSG, purpose="test")
    assert fake.requests == []  # resting keys are not called at all


async def test_no_keys_means_not_configured() -> None:
    gateway = make_gateway(FakeAPI(lambda c: ok()), or_keys=[], groq_keys=[])
    with pytest.raises(LLMNotConfiguredError):
        await gateway.complete(MSG, purpose="test")


async def test_prompts_over_the_groq_limit_skip_groq() -> None:
    fake = FakeAPI(lambda c: ok())
    gateway = make_gateway(fake, or_keys=[], groq_max_prompt_tokens=500)
    long_prompt = [{"role": "user", "content": "x" * 4000}]  # about 1,000 tokens

    with pytest.raises(LLMRejectedError, match="too long for groq"):
        await gateway.complete(long_prompt, purpose="test")
    assert fake.requests == []


async def test_models_reported_missing_are_skipped() -> None:
    fake = FakeAPI(lambda c: ok())
    gateway = make_gateway(fake)
    gateway.providers[0].catalog["or/fast"].status = "missing"

    result = await gateway.complete(MSG, purpose="test")

    assert result.provider == "groq"


async def test_fast_tier_asks_for_low_reasoning_effort() -> None:
    fake = FakeAPI(lambda c: ok())
    gateway = make_gateway(fake)
    await gateway.complete(MSG, purpose="test", tier="fast")
    await gateway.complete(MSG, purpose="test", tier="smart")

    assert fake.requests[0]["body"]["reasoning"] == {"effort": "low"}
    assert "reasoning" not in fake.requests[1]["body"]


# ── Structured output ────────────────────────────────────────────────────────


class Answer(BaseModel):
    sql: str
    confidence: float


async def test_complete_json_reads_the_submit_tool_call() -> None:
    fake = FakeAPI(lambda c: ok(tool_args={"sql": "SELECT 1", "confidence": 0.9}))
    gateway = make_gateway(fake)

    answer, result = await gateway.complete_json(MSG, Answer, purpose="test")

    assert answer == Answer(sql="SELECT 1", confidence=0.9)
    assert result.model == "or/smart-a"
    body = fake.requests[0]["body"]
    assert body["tools"][0]["function"]["name"] == "submit"
    assert "tool_choice" not in body  # support unknown, so the tool is offered, not forced


async def test_tool_call_is_forced_only_where_the_model_supports_it() -> None:
    fake = FakeAPI(lambda c: ok(tool_args={"sql": "SELECT 1", "confidence": 1}))
    gateway = make_gateway(fake)
    gateway.providers[0].catalog["or/smart-a"].supports_tool_choice = True

    await gateway.complete_json(MSG, Answer, purpose="test")

    assert fake.requests[0]["body"]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit"},
    }


async def test_complete_json_accepts_json_text_and_retries_invalid_answers() -> None:
    replies = iter(
        [
            ok('I think {"sql": 42}'),
            ok('```json\n{"sql": "SELECT 2", "confidence": 1}\n```'),
        ]
    )
    fake = FakeAPI(lambda c: next(replies))
    gateway = make_gateway(fake)

    answer, _ = await gateway.complete_json(MSG, Answer, purpose="test")

    assert answer.sql == "SELECT 2"
    assert "could not be used" in fake.requests[1]["body"]["messages"][-1]["content"]


async def test_complete_json_gives_up_after_one_retry() -> None:
    fake = FakeAPI(lambda c: ok("no json here"))
    gateway = make_gateway(fake)
    with pytest.raises(LLMInvalidOutputError):
        await gateway.complete_json(MSG, Answer, purpose="test")
    assert len(fake.requests) == 2


# ── Streaming ────────────────────────────────────────────────────────────────


async def test_stream_reports_thinking_text_and_usage() -> None:
    fake = FakeAPI(
        lambda c: sse(
            chunk(reasoning="Let me think"),
            chunk("Hel"),
            chunk("lo"),
            chunk(finish="stop", usage={"prompt_tokens": 9, "completion_tokens": 2}),
        )
    )
    records: list[CallRecord] = []
    gateway = make_gateway(fake, records=records)

    events = [event async for event in gateway.stream(MSG, purpose="test")]

    assert events[0] == StreamStart("openrouter", "or/fast", 1)
    assert events[1] == StreamThinking()
    assert [e.text for e in events if isinstance(e, StreamDelta)] == ["Hel", "lo"]
    end = events[-1]
    assert isinstance(end, StreamEnd)
    assert (end.usage, end.finish_reason) == (Usage(9, 2), "stop")
    assert fake.requests[0]["body"]["stream"] is True
    assert [r.outcome for r in records] == ["ok"]


async def test_stream_switches_key_before_the_first_chunk() -> None:
    fake = FakeAPI(
        lambda c: fail(429, "busy") if c["key"] == 1 else sse(chunk("ok"), chunk(finish="stop"))
    )
    gateway = make_gateway(fake)

    events = [event async for event in gateway.stream(MSG, purpose="test")]

    assert events[0] == StreamStart("openrouter", "or/fast", 2)


async def test_stream_failing_midway_raises_interrupted() -> None:
    fake = FakeAPI(lambda c: sse(chunk("partial"), {"error": {"message": "upstream died"}}))
    gateway = make_gateway(fake)

    received = []
    with pytest.raises(LLMStreamInterruptedError):
        async for event in gateway.stream(MSG, purpose="test"):
            received.append(event)
    assert StreamDelta("partial") in received


# ── Model check and status ───────────────────────────────────────────────────


async def test_check_models_flags_missing_models_and_reads_tool_support() -> None:
    def respond(c: Call) -> httpx2.Response:
        if c["provider"] == "openrouter":
            models = [
                {"id": "or/smart-a", "supported_parameters": ["tools", "tool_choice"]},
                {"id": "or/fast", "supported_parameters": ["tools"]},
            ]
        else:
            models = [{"id": "groq/smart"}, {"id": "groq/fast"}]
        return httpx2.Response(200, json={"object": "list", "data": models})

    gateway = make_gateway(FakeAPI(respond))
    await gateway.check_models()

    catalog = gateway.providers[0].catalog
    assert catalog["or/smart-a"].supports_tool_choice is True
    assert catalog["or/fast"].supports_tool_choice is False
    assert catalog["or/smart-b"].status == "missing"
    assert {model.check for model in gateway.status()[1].models} == {"ok"}


async def test_status_shows_masked_keys_only() -> None:
    gateway = make_gateway(FakeAPI(lambda c: fail(401)))
    with pytest.raises(LLMUnavailableError):
        await gateway.complete(MSG, purpose="test")

    status = gateway.status()
    dumped = "".join(provider.model_dump_json() for provider in status)
    assert not any(key in dumped for key in OR_KEYS + GROQ_KEYS)
    assert status[0].keys[0].masked == "sk-or-...0000"
    assert status[0].keys[0].state == "disabled"


async def test_a_model_that_calls_a_tool_it_was_not_given_is_asked_again_without_tools() -> None:
    def respond(call: Call) -> httpx2.Response:
        if "tools" in call["body"]:
            return fail(
                400,
                "Tool call validation failed: attempted to call tool 'json' which was not in "
                "request.tools",
            )
        return ok('{"sql": "SELECT 1", "confidence": 0.5}')

    fake = FakeAPI(respond)
    gateway = make_gateway(fake)

    answer, result = await gateway.complete_json(MSG, Answer, purpose="test")

    assert answer == Answer(sql="SELECT 1", confidence=0.5)
    assert result.model == "or/smart-a"  # the same model answered, without the tool
    assert ["tools" in c["body"] for c in fake.requests] == [True, False]
    assert gateway.providers[0].pool.keys[0].failures == 0


async def test_rejected_keys_are_named_as_the_problem_not_a_busy_service() -> None:
    fake = FakeAPI(
        lambda c: fail(401, "bad key") if c["provider"] == "openrouter" else fail(400, "nope")
    )
    gateway = make_gateway(fake)

    with pytest.raises(LLMUnavailableError) as caught:
        await gateway.complete(MSG, purpose="test", tier="smart")

    assert "rejected its API key" in str(caught.value) and "System status" in str(caught.value)
    assert "busy" not in str(caught.value)
