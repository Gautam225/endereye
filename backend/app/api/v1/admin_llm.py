"""Admin tools for the LLM gateway: key and model health."""

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_admin
from app.db.models import LLMCall
from app.llm.gateway import LLMDep
from app.schemas.llm import LLMStatusResponse, RecentCalls

router = APIRouter(prefix="/admin/llm", tags=["admin"], dependencies=[Depends(require_admin)])

RECENT_WINDOW_HOURS = 24


@router.get("/status", response_model=LLMStatusResponse)
async def llm_status(request: Request, llm: LLMDep) -> LLMStatusResponse:
    """Health of every key (masked) and model, plus call counts from the last 24 hours."""
    return LLMStatusResponse(
        providers=llm.status(),
        recent_calls=await _recent_calls(request.app.state.sessionmaker),
    )


async def _recent_calls(sessionmaker: async_sessionmaker[AsyncSession]) -> RecentCalls | None:
    since = datetime.now(UTC) - timedelta(hours=RECENT_WINDOW_HOURS)
    query = (
        select(LLMCall.provider, LLMCall.outcome, func.count())
        .where(LLMCall.created_at >= since)
        .group_by(LLMCall.provider, LLMCall.outcome)
    )
    try:
        async with asyncio.timeout(3), sessionmaker() as session:
            rows = (await session.execute(query)).all()
    except Exception:
        return None  # the status page still works without history

    by_outcome: Counter[str] = Counter()
    by_provider: Counter[str] = Counter()
    for provider, outcome, count in rows:
        by_outcome[outcome] += count
        by_provider[provider] += count
    return RecentCalls(
        window_hours=RECENT_WINDOW_HOURS,
        total=sum(by_outcome.values()),
        by_outcome=dict(by_outcome),
        by_provider=dict(by_provider),
    )
