"""One configured LLM provider (OpenRouter or Groq): its keys, models, and HTTP clients."""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio
import httpx2
from openai import AsyncOpenAI

from app.core.config import Settings
from app.llm.key_pool import ApiKey, KeyPool
from app.llm.types import Tier

logger = logging.getLogger(__name__)

MODEL_CHECK_TIMEOUT_SECONDS = 15


@dataclass
class ModelInfo:
    status: Literal["ok", "missing", "unchecked", "error"] = "unchecked"
    detail: str | None = "Not checked yet."
    supports_tool_choice: bool | None = None  # None = unknown


@dataclass
class Provider:
    name: Literal["openrouter", "groq"]
    role: Literal["primary", "fallback"]
    base_url: str
    pool: KeyPool
    models: dict[Tier, list[str]]
    timeout: float
    max_prompt_tokens: int | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    http_client: httpx2.AsyncClient | None = None  # injected by tests
    catalog: dict[str, ModelInfo] = field(default_factory=dict)
    _clients: dict[int, AsyncOpenAI] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for model in self.all_models:
            self.catalog.setdefault(model, ModelInfo())

    @property
    def all_models(self) -> list[str]:
        return list(dict.fromkeys(self.models["smart"] + self.models["fast"]))

    def client(self, key: ApiKey) -> AsyncOpenAI:
        client = self._clients.get(key.index)
        if client is None:
            client = AsyncOpenAI(
                api_key=key.secret,
                base_url=self.base_url,
                max_retries=0,  # the key pool is the only retry logic
                timeout=self.timeout,
                default_headers=self.default_headers or None,
                http_client=self.http_client,
            )
            self._clients[key.index] = client
        return client

    def request_options(self, model: str, tier: Tier) -> dict[str, Any]:
        """Provider-specific options. The fast tier asks reasoning models to think briefly."""
        if tier != "fast":
            return {}
        if self.name == "openrouter":
            # OpenRouter's unified reasoning setting; models that don't reason ignore it.
            return {"extra_body": {"reasoning": {"effort": "low"}}}
        if model.startswith("openai/gpt-oss"):
            return {"reasoning_effort": "low"}
        return {}

    def can_force_tool(self, model: str) -> bool:
        if self.name == "groq":
            return True
        return self.catalog[model].supports_tool_choice is True

    async def check_models(self) -> None:
        """Compare the configured model ids with the provider's live model list."""
        if not self.pool.configured:
            for model in self.all_models:
                self.catalog[model] = ModelInfo("unchecked", "No API keys configured.")
            return

        client = self.client(self.pool.keys[0])
        try:
            async with asyncio.timeout(MODEL_CHECK_TIMEOUT_SECONDS):
                offered = {model.id: model async for model in client.models.list()}
        except Exception as exc:
            detail = f"Could not load the model list ({type(exc).__name__})."
            for model in self.all_models:
                self.catalog[model] = ModelInfo("error", detail)
            logger.warning("%s model check failed: %s", self.name, detail)
            return

        for model in self.all_models:
            info = offered.get(model)
            if info is None:
                self.catalog[model] = ModelInfo(
                    "missing", "The provider no longer offers this model. Change it in .env."
                )
                logger.warning("%s does not offer %s - change it in .env", self.name, model)
                continue
            params = (info.model_extra or {}).get("supported_parameters")
            self.catalog[model] = ModelInfo(
                "ok", None, ("tool_choice" in params) if isinstance(params, list) else None
            )
        logger.info("%s models checked", self.name)

    async def aclose(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        if self.http_client is not None:
            return  # whoever injected the HTTP client closes it
        with anyio.CancelScope(shield=True):
            for client in clients:
                await client.close()


def build_providers(
    settings: Settings,
    *,
    http_client: httpx2.AsyncClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[Provider]:
    def pool(keys: list[Any]) -> KeyPool:
        return KeyPool(
            [key.get_secret_value() for key in keys],
            rate_limit_cooldown=settings.llm_rate_limit_cooldown_seconds,
            clock=clock,
        )

    return [
        Provider(
            name="openrouter",
            role="primary",
            base_url=settings.openrouter_base_url,
            pool=pool(settings.openrouter_api_keys),
            models={
                "smart": settings.openrouter_models_smart,
                "fast": settings.openrouter_models_fast,
            },
            timeout=settings.llm_attempt_timeout_seconds,
            default_headers={"X-Title": settings.app_name},
            http_client=http_client,
        ),
        Provider(
            name="groq",
            role="fallback",
            base_url=settings.groq_base_url,
            pool=pool(settings.groq_api_keys),
            models={"smart": settings.groq_models_smart, "fast": settings.groq_models_fast},
            timeout=settings.llm_attempt_timeout_seconds,
            max_prompt_tokens=settings.groq_max_prompt_tokens,
            http_client=http_client,
        ),
    ]
