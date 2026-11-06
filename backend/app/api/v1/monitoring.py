"""Administrator monitoring: how the assistant is doing, and a review queue for bad answers."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SettingsDep, require_admin
from app.db.session import SessionDep
from app.schemas.monitoring import (
    CorrectionIn,
    CorrectionOut,
    FeedbackFilter,
    MessageStatusName,
    MonitorDetail,
    MonitoringSummary,
    MonitorList,
    ReviewFilter,
    ReviewIn,
)
from app.services import monitoring as service

router = APIRouter(
    prefix="/admin/monitoring", tags=["admin"], dependencies=[Depends(require_admin)]
)

Days = Annotated[int, Query(ge=1, le=365, description="Look back this many days")]
DateFrom = Annotated[date | None, Query(description="Start date (inclusive); overrides days")]
DateTo = Annotated[date | None, Query(description="End date (inclusive)")]


@router.get("/summary", response_model=MonitoringSummary)
async def summary(
    session: SessionDep,
    days: Days = 30,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    space_id: uuid.UUID | None = None,
) -> MonitoringSummary:
    """Volumes, failures, speed and feedback over a period, with a per-day series."""
    return await service.summary(session, days, date_from, date_to, space_id)


@router.get("/messages", response_model=MonitorList)
async def list_messages(
    session: SessionDep,
    days: Days = 30,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    space_id: uuid.UUID | None = None,
    status: MessageStatusName | None = None,
    feedback: FeedbackFilter | None = None,
    review: ReviewFilter | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Search the questions")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MonitorList:
    """Every question asked, newest first, filtered by date, status, feedback or review."""
    return await service.list_messages(
        session,
        days=days,
        date_from=date_from,
        date_to=date_to,
        space_id=space_id,
        status=status,
        feedback=feedback,
        review=review,
        query=q,
        limit=limit,
        offset=offset,
    )


@router.get("/messages/{message_id}", response_model=MonitorDetail)
async def message_detail(message_id: uuid.UUID, session: SessionDep) -> MonitorDetail:
    """One answer with its SQL and what went wrong. Result rows are not included."""
    return await service.detail(session, message_id)


@router.post("/messages/{message_id}/review", response_model=MonitorDetail)
async def review(
    message_id: uuid.UUID, body: ReviewIn, admin: CurrentUser, session: SessionDep
) -> MonitorDetail:
    """Mark an answer as resolved, dismissed, or open again, with a note."""
    return await service.review(session, message_id, admin, body)


@router.post("/messages/{message_id}/correct", response_model=CorrectionOut)
async def correct(
    message_id: uuid.UUID,
    body: CorrectionIn,
    admin: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> CorrectionOut:
    """Save a verified question and SQL as an example for the space (and resolve the review).
    The SQL is checked and run first; a query that fails cannot become an example."""
    return await service.correct(session, message_id, admin, body, settings)
