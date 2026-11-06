"""Shared types for the LLM gateway."""

from dataclasses import dataclass
from typing import Any, Literal

Tier = Literal["smart", "fast"]
TIERS: tuple[Tier, ...] = ("smart", "fast")

# OpenAI chat format, e.g. {"role": "user", "content": "..."}
Message = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: str  # JSON text, exactly as the model sent it


@dataclass(frozen=True, slots=True)
class LLMResult:
    text: str
    provider: str
    model: str
    key_index: int
    latency_ms: int
    usage: Usage
    finish_reason: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class StreamStart:
    provider: str
    model: str
    key_index: int


@dataclass(frozen=True, slots=True)
class StreamThinking:
    """The model started reasoning. Sent at most once, before any answer text."""


@dataclass(frozen=True, slots=True)
class StreamDelta:
    text: str


@dataclass(frozen=True, slots=True)
class StreamEnd:
    latency_ms: int
    usage: Usage
    finish_reason: str | None


StreamEvent = StreamStart | StreamThinking | StreamDelta | StreamEnd


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One attempt against one provider, model, and key; stored in `llm_calls`."""

    provider: str
    model: str
    key_index: int
    tier: str
    purpose: str
    outcome: str
    latency_ms: int
    http_status: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    request_id: str | None = None
