"""The LLM gateway: the one place the app calls a model.

Every call goes: OpenRouter keys (round-robin) -> Groq keys. Within a provider, the tier's
models are tried in order. What happens on each kind of failure: docs/ROADMAP.md, 4.1.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

import anyio
import httpx2
import openai
from fastapi import Depends, Request
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.logging import request_id_var
from app.llm.errors import (
    LLMInvalidOutputError,
    LLMNotConfiguredError,
    LLMRejectedError,
    LLMStreamInterruptedError,
    LLMUnavailableError,
)
from app.llm.failures import (
    BAD_REQUEST,
    DATA_POLICY,
    INVALID_KEY,
    Failure,
    ProviderResponseError,
    classify,
)
from app.llm.key_pool import ApiKey
from app.llm.providers import Provider, build_providers
from app.llm.types import (
    TIERS,
    CallRecord,
    LLMResult,
    Message,
    StreamDelta,
    StreamEnd,
    StreamEvent,
    StreamStart,
    StreamThinking,
    Tier,
    ToolCall,
    Usage,
)
from app.schemas.llm import KeyStatus, ModelStatus, ProviderStatus

logger = logging.getLogger(__name__)

T = TypeVar("T")
SchemaT = TypeVar("SchemaT", bound=BaseModel)
Recorder = Callable[[CallRecord], None]

# Errors that mean "this attempt failed, try the next key/model/provider".
RETRYABLE = (openai.APIError, httpx2.HTTPError, ProviderResponseError)
SUBMIT_TOOL = "submit"
_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def estimate_tokens(messages: list[Message]) -> int:
    """Rough count (about 4 characters per token); enough to respect provider limits."""
    characters = sum(len(str(message.get("content") or "")) for message in messages)
    return characters // 4 + 4 * len(messages)


@dataclass(slots=True)
class _OpenStream:
    stream: AsyncStream[ChatCompletionChunk]
    chunks: AsyncIterator[ChatCompletionChunk]
    first: ChatCompletionChunk | None


@dataclass(slots=True)
class _Attempt:
    value: Any
    provider: Provider
    model: str
    key: ApiKey
    started: float


class LLMGateway:
    def __init__(
        self,
        providers: list[Provider],
        *,
        recorder: Recorder | None = None,
        total_timeout: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = providers
        self._recorder = recorder
        self._total_timeout = total_timeout
        self._clock = clock

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        recorder: Recorder | None = None,
        http_client: httpx2.AsyncClient | None = None,
    ) -> "LLMGateway":
        return cls(
            build_providers(settings, http_client=http_client),
            recorder=recorder,
            total_timeout=settings.llm_total_timeout_seconds,
        )

    @property
    def configured(self) -> bool:
        return any(provider.pool.configured for provider in self.providers)

    async def check_models(self) -> None:
        await asyncio.gather(*(provider.check_models() for provider in self.providers))

    async def aclose(self) -> None:
        for provider in self.providers:
            await provider.aclose()

    # ── Calls ────────────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[Message],
        *,
        purpose: str,
        tier: Tier = "fast",
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        force_tool: str | None = None,
    ) -> LLMResult:
        async def attempt(provider: Provider, model: str, key: ApiKey, seconds: float) -> Any:
            options = self._options(provider, model, tier, temperature, max_tokens)
            if tools:
                options["tools"] = tools
                if force_tool and provider.can_force_tool(model):
                    options["tool_choice"] = {"type": "function", "function": {"name": force_tool}}
            client = provider.client(key)
            try:
                response = await client.chat.completions.create(
                    model=model, messages=messages, timeout=seconds, **options
                )
            except openai.BadRequestError as exc:
                # Some models (gpt-oss on Groq) call a tool that was never offered. The
                # instructions already allow a JSON answer in plain text, so ask again
                # without tools instead of giving up on the model.
                if not tools or "tool call validation failed" not in str(exc).lower():
                    raise
                options.pop("tools", None)
                options.pop("tool_choice", None)
                response = await client.chat.completions.create(
                    model=model, messages=messages, timeout=seconds, **options
                )
            if not response.choices:
                raise ProviderResponseError("The provider returned an empty answer.")
            return response

        done = await self._execute(tier, messages, purpose, attempt)
        response = done.value
        choice = response.choices[0]
        usage = (
            Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
            if response.usage
            else Usage()
        )
        tool_calls = tuple(
            ToolCall(call.function.name, call.function.arguments or "")
            for call in choice.message.tool_calls or ()
            if getattr(call, "function", None) is not None
        )
        self._record(done, tier, purpose, outcome="ok", usage=usage)
        return LLMResult(
            text=choice.message.content or "",
            provider=done.provider.name,
            model=done.model,
            key_index=done.key.index,
            latency_ms=self._elapsed_ms(done.started),
            usage=usage,
            finish_reason=choice.finish_reason,
            tool_calls=tool_calls,
        )

    async def complete_json(
        self,
        messages: list[Message],
        schema: type[SchemaT],
        *,
        purpose: str,
        tier: Tier = "smart",
    ) -> tuple[SchemaT, LLMResult]:
        """Structured output via a `submit` tool call, validated with Pydantic.

        Models that can't be forced to call the tool may answer with JSON text instead; that
        is accepted too. One retry, with the validation problem explained to the model.
        """
        json_schema = schema.model_json_schema()
        tool = {
            "type": "function",
            "function": {
                "name": SUBMIT_TOOL,
                "description": "Submit the final answer.",
                "parameters": json_schema,
            },
        }
        conversation = _with_instructions(messages, _json_instructions(json_schema))
        for _ in range(2):
            result = await self.complete(
                conversation, purpose=purpose, tier=tier, tools=[tool], force_tool=SUBMIT_TOOL
            )
            payload = next(
                (call.arguments for call in result.tool_calls if call.name == SUBMIT_TOOL), None
            ) or _extract_json(result.text)
            if payload is None:
                problem = "no JSON answer was found"
            else:
                try:
                    return schema.model_validate_json(payload), result
                except ValidationError as exc:
                    problem = _summarize(exc)
            conversation = [
                *conversation,
                {
                    "role": "user",
                    "content": f"Your last reply could not be used ({problem}). Call the "
                    f"`{SUBMIT_TOOL}` tool once, with arguments that match its schema exactly.",
                },
            ]
        raise LLMInvalidOutputError(
            "The AI model did not return a usable answer. Please try again."
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        purpose: str,
        tier: Tier = "fast",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream an answer. Switching key/provider is only possible before the first chunk."""

        async def attempt(provider: Provider, model: str, key: ApiKey, seconds: float) -> Any:
            stream = await provider.client(key).chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                timeout=seconds,
                **self._options(provider, model, tier, temperature, max_tokens),
            )
            chunks = stream.__aiter__()
            try:
                first = await anext(chunks, None)
            except BaseException:
                await _close_quietly(stream)
                raise
            return _OpenStream(stream, chunks, first)

        done = await self._execute(tier, messages, purpose, attempt)
        opened: _OpenStream = done.value
        yield StreamStart(done.provider.name, done.model, done.key.index)

        usage, finish_reason, thinking = Usage(), None, False
        outcome, error = "ok", None
        try:
            chunk = opened.first
            while chunk is not None:
                usage = _chunk_usage(chunk) or usage
                for choice in chunk.choices:
                    delta = choice.delta
                    if delta is not None:
                        if not thinking and _has_reasoning(delta):
                            thinking = True
                            yield StreamThinking()
                        if delta.content:
                            yield StreamDelta(delta.content)
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                chunk = await anext(opened.chunks, None)
        except RETRYABLE as exc:
            failure = classify(exc)
            outcome, error = failure.outcome, failure.message
            raise LLMStreamInterruptedError(
                "The answer was cut off by the AI provider. Please try again."
            ) from exc
        except (asyncio.CancelledError, GeneratorExit):
            outcome = "cancelled"  # the client went away
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            await _close_quietly(opened.stream)
            self._record(done, tier, purpose, outcome=outcome, usage=usage, error=error)
        yield StreamEnd(self._elapsed_ms(done.started), usage, finish_reason)

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> list[ProviderStatus]:
        return [
            ProviderStatus(
                name=provider.name,
                role=provider.role,
                configured=provider.pool.configured,
                max_prompt_tokens=provider.max_prompt_tokens,
                keys=[_key_status(provider, key) for key in provider.pool.keys],
                models=[
                    ModelStatus(
                        id=model,
                        tiers=[tier for tier in TIERS if model in provider.models[tier]],
                        check=provider.catalog[model].status,
                        detail=provider.catalog[model].detail,
                    )
                    for model in provider.all_models
                ],
            )
            for provider in self.providers
        ]

    # ── Internals ────────────────────────────────────────────────────────────

    async def _execute(
        self,
        tier: Tier,
        messages: list[Message],
        purpose: str,
        attempt: Callable[[Provider, str, ApiKey, float], Awaitable[Any]],
    ) -> _Attempt:
        """Run `attempt` on each provider -> model -> key in order until one succeeds."""
        if not self.configured:
            raise LLMNotConfiguredError()

        deadline = self._clock() + self._total_timeout
        prompt_tokens = estimate_tokens(messages)
        failures: list[Failure] = []

        for provider in self.providers:
            if not provider.pool.configured:
                continue
            if (
                provider.max_prompt_tokens is not None
                and prompt_tokens > provider.max_prompt_tokens
            ):
                logger.info(
                    "Skipping %s: prompt of about %d tokens is over its limit of %d",
                    provider.name,
                    prompt_tokens,
                    provider.max_prompt_tokens,
                )
                failures.append(
                    Failure(BAD_REQUEST, f"The prompt is too long for {provider.name}.")
                )
                continue

            rotation = provider.pool.rotation()
            for model in provider.models[tier]:
                if provider.catalog[model].status == "missing":
                    continue
                for key in rotation:
                    if not provider.pool.is_available(key, model):
                        continue
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise LLMUnavailableError(
                            "The AI service is taking too long to respond. Please try again."
                        )
                    started = self._clock()
                    try:
                        value = await attempt(
                            provider, model, key, min(provider.timeout, remaining)
                        )
                    except RETRYABLE as exc:
                        failure = classify(exc)
                        failures.append(failure)
                        provider.pool.record_failure(key, model, failure)
                        self._record(
                            _Attempt(None, provider, model, key, started),
                            tier,
                            purpose,
                            outcome=failure.outcome,
                            http_status=failure.http_status,
                            error=failure.message,
                        )
                        if failure.is_request_problem:
                            break  # another key would fail the same way: next model
                        continue
                    provider.pool.record_success(key, model)
                    return _Attempt(value, provider, model, key, started)

        raise self._exhausted(tier, failures)

    def _exhausted(self, tier: Tier, failures: list[Failure]) -> Exception:
        if failures and all(failure.is_request_problem for failure in failures):
            return LLMRejectedError(
                f"The AI model could not handle this request: {failures[-1].message}"
            )
        if any(failure.outcome in {INVALID_KEY, DATA_POLICY} for failure in failures):
            return LLMUnavailableError(
                "No AI model could answer: a provider rejected its API key. "
                "An admin can see which one, and how to fix it, on System status."
            )
        waits = [
            wait
            for provider in self.providers
            if provider.pool.configured
            and (wait := provider.pool.seconds_until_available(provider.models[tier])) is not None
        ]
        if not waits:
            return LLMUnavailableError(
                "Every AI key is disabled. Open System status to see why and how to fix it."
            )
        wait = min(waits)
        if wait < 1:
            return LLMUnavailableError("The AI service is busy right now. Please try again.")
        return LLMUnavailableError(
            f"The AI service is busy right now. Try again in {_human_duration(wait)}.",
            retry_after=wait,
        )

    @staticmethod
    def _options(
        provider: Provider,
        model: str,
        tier: Tier,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        options = provider.request_options(model, tier)
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        return options

    def _record(
        self,
        attempt: _Attempt,
        tier: Tier,
        purpose: str,
        *,
        outcome: str,
        usage: Usage | None = None,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        latency_ms = self._elapsed_ms(attempt.started)
        fields = {
            "provider": attempt.provider.name,
            "model": attempt.model,
            "key": attempt.key.index,
            "outcome": outcome,
            "latency_ms": latency_ms,
        }
        if outcome in ("ok", "cancelled"):
            logger.info("LLM call", extra=fields)
        else:
            logger.warning("LLM call failed", extra={**fields, "detail": error})

        if self._recorder is not None:
            self._recorder(
                CallRecord(
                    provider=attempt.provider.name,
                    model=attempt.model,
                    key_index=attempt.key.index,
                    tier=tier,
                    purpose=purpose,
                    outcome=outcome,
                    latency_ms=latency_ms,
                    http_status=http_status,
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                    error=error[:500] if error else None,
                    request_id=request_id_var.get(),
                )
            )

    def _elapsed_ms(self, started: float) -> int:
        return round((self._clock() - started) * 1000)


def get_llm(request: Request) -> LLMGateway:
    return request.app.state.llm


LLMDep = Annotated[LLMGateway, Depends(get_llm)]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _key_status(provider: Provider, key: ApiKey) -> KeyStatus:
    rest = round(provider.pool.seconds_left(key.rest_until))
    model_rests = {
        model: round(provider.pool.seconds_left(until))
        for model, until in key.model_rest_until.items()
        if provider.pool.seconds_left(until) >= 1
    }
    if key.disabled_reason:
        state = "disabled"
    elif rest >= 1 or all(model in model_rests for model in provider.all_models):
        state = "resting"
    else:
        state = "ready"
    return KeyStatus(
        index=key.index,
        masked=key.masked,
        state=state,
        rest_seconds=rest,
        model_rests=model_rests,
        reason=key.disabled_reason,
        last_error=key.last_error,
        successes=key.successes,
        failures=key.failures,
        last_used_at=key.last_used_at,
    )


async def _close_quietly(stream: AsyncStream[ChatCompletionChunk]) -> None:
    # Shielded: when the client disconnects, this runs inside a cancelled scope.
    with anyio.CancelScope(shield=True):
        try:
            await stream.close()
        except Exception:
            logger.debug("Closing an LLM stream failed", exc_info=True)


def _chunk_usage(chunk: ChatCompletionChunk) -> Usage | None:
    usage: Any = chunk.usage
    if usage is None:
        usage = ((chunk.model_extra or {}).get("x_groq") or {}).get("usage")  # Groq
    if usage is None:
        return None
    if isinstance(usage, dict):
        return Usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
    return Usage(usage.prompt_tokens, usage.completion_tokens)


def _has_reasoning(delta: Any) -> bool:
    extra = delta.model_extra or {}
    return bool(extra.get("reasoning") or extra.get("reasoning_content"))


def _json_instructions(json_schema: dict[str, Any]) -> str:
    return (
        f"When you have the answer, call the `{SUBMIT_TOOL}` tool with it. If you cannot call "
        "tools, reply with only a JSON object (no other text) matching this JSON schema:\n"
        + json.dumps(json_schema)
    )


def _with_instructions(messages: list[Message], text: str) -> list[Message]:
    if messages and messages[0].get("role") == "system":
        first = messages[0]
        return [{**first, "content": f"{first.get('content') or ''}\n\n{text}"}, *messages[1:]]
    return [{"role": "system", "content": text}, *messages]


def _extract_json(text: str) -> str | None:
    match = _JSON_FENCE.search(text)
    if match:
        return match.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else None


def _summarize(exc: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(p) for p in error['loc']) or 'answer'}: {error['msg']}"
        for error in exc.errors()[:3]
    ]
    return "; ".join(parts)


def _human_duration(seconds: float) -> str:
    seconds = max(1, round(seconds))
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds / 3600)} hours"
