"""Saves every LLM attempt to `llm_calls` in the background, so requests never wait on it."""

import asyncio
import logging
import time
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import LLMCall
from app.llm.types import CallRecord

logger = logging.getLogger(__name__)

WARN_EVERY_SECONDS = 60


class CallRecorder:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._pending: set[asyncio.Task[None]] = set()
        self._last_warning = float("-inf")

    def __call__(self, record: CallRecord) -> None:
        task = asyncio.create_task(self._save(record))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _save(self, record: CallRecord) -> None:
        try:
            async with self._sessionmaker() as session:
                session.add(LLMCall(**asdict(record)))
                await session.commit()
        except Exception as exc:
            # The LLM call itself worked; only the history is lost. Warn, but not on every call.
            now = time.monotonic()
            if now - self._last_warning >= WARN_EVERY_SECONDS:
                self._last_warning = now
                logger.warning("Could not save LLM call history (%s)", type(exc).__name__)

    async def aclose(self) -> None:
        if self._pending:
            await asyncio.wait(self._pending, timeout=5)
