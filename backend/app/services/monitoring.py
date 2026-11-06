"""What the assistant is doing across all spaces: volumes, failures, speed, feedback, review.

For administrators only. It shows what was asked, the SQL, timings and feedback, but never the
rows a query returned. User feedback is a signal for review, never trusted as correct SQL: only
an administrator's verified correction becomes an example.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import (
    Conversation,
    KnowledgeItem,
    Message,
    MessageStatus,
    Space,
    SpaceRole,
    User,
)
from app.schemas.monitoring import (
    CorrectionIn,
    CorrectionOut,
    DayPoint,
    MonitorDetail,
    MonitoringSummary,
    MonitorList,
    MonitorRow,
    ReviewIn,
)
from app.services import indexing, spaces
from app.services.spaces import SpaceAccess

DEFAULT_DAYS = 30
FINISHED = (
    MessageStatus.OK.value,
    MessageStatus.EMPTY.value,
    MessageStatus.ANSWER.value,
    MessageStatus.CLARIFY.value,
    MessageStatus.DECLINED.value,
    MessageStatus.FAILED.value,
)

total_ms = Message.timings["total"].as_integer()
execute_ms = Message.timings["execute"].as_integer()
needs_review = and_(
    or_(Message.feedback == "down", Message.status == MessageStatus.FAILED.value),
    or_(Message.review_status.is_(None), Message.review_status == "open"),
)


def window(days: int, date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    """The time range to look at: explicit dates (inclusive) or the last `days` days."""
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        if date_to
        else datetime.now(UTC) + timedelta(seconds=1)
    )
    start = datetime.combine(date_from, time.min, UTC) if date_from else end - timedelta(days=days)
    return start, end


def _scope(statement: Select, start: datetime, end: datetime, space_id: uuid.UUID | None) -> Select:
    statement = statement.where(Message.created_at >= start, Message.created_at < end)
    if space_id is not None:
        statement = statement.where(Conversation.space_id == space_id)
    return statement


def _joined(*columns) -> Select:
    return (
        select(*columns)
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
    )


async def summary(
    session: AsyncSession,
    days: int,
    date_from: date | None,
    date_to: date | None,
    space_id: uuid.UUID | None,
) -> MonitoringSummary:
    start, end = window(days, date_from, date_to)
    by_status = dict(
        (
            await session.execute(
                _scope(_joined(Message.status, func.count()), start, end, space_id).group_by(
                    Message.status
                )
            )
        ).all()
    )
    questions = sum(by_status.values())
    finished = sum(by_status.get(s, 0) for s in FINISHED)

    answered = Message.status.in_(
        [MessageStatus.OK.value, MessageStatus.EMPTY.value, MessageStatus.ANSWER.value]
    )
    speed = (
        await session.execute(
            _scope(
                _joined(
                    func.avg(total_ms),
                    func.percentile_cont(0.95).within_group(total_ms),
                    func.avg(execute_ms),
                ),
                start,
                end,
                space_id,
            ).where(answered)
        )
    ).one()
    feedback = (
        await session.execute(
            _scope(
                _joined(
                    func.count().filter(Message.feedback == "up"),
                    func.count().filter(Message.feedback == "down"),
                    func.count().filter(needs_review),
                ),
                start,
                end,
                space_id,
            )
        )
    ).one()
    day = func.date_trunc("day", Message.created_at)
    series = (
        await session.execute(
            _scope(
                _joined(
                    day,
                    func.count(),
                    func.count().filter(Message.status == MessageStatus.FAILED.value),
                    func.count().filter(Message.feedback == "down"),
                ),
                start,
                end,
                space_id,
            )
            .group_by(day)
            .order_by(day)
        )
    ).all()
    return MonitoringSummary(
        days=days,
        questions=questions,
        by_status=by_status,
        failure_rate=round(by_status.get(MessageStatus.FAILED.value, 0) / finished, 4)
        if finished
        else 0.0,
        avg_total_ms=None if speed[0] is None else round(speed[0]),
        p95_total_ms=None if speed[1] is None else round(speed[1]),
        avg_execute_ms=None if speed[2] is None else round(speed[2]),
        thumbs_up=feedback[0],
        thumbs_down=feedback[1],
        needs_review=feedback[2],
        by_day=[
            DayPoint(day=d.date(), questions=q, failed=f, thumbs_down=t) for d, q, f, t in series
        ],
    )


def _row(message: Message, space: Space, user: User) -> dict:
    return {
        "id": message.id,
        "created_at": message.created_at,
        "space_id": space.id,
        "space_name": space.name,
        "user_name": user.full_name,
        "question": message.question,
        "status": message.status,
        "error_code": message.error_code,
        "attempts": message.attempts,
        "total_ms": message.timings.get("total"),
        "execute_ms": message.timings.get("execute"),
        "trusted": message.trusted,
        "row_count": message.row_count,
        "feedback": message.feedback,
        "feedback_comment": message.feedback_comment,
        "review_status": message.review_status,
    }


async def list_messages(
    session: AsyncSession,
    *,
    days: int,
    date_from: date | None,
    date_to: date | None,
    space_id: uuid.UUID | None,
    status: str | None,
    feedback: str | None,
    review: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> MonitorList:
    start, end = window(days, date_from, date_to)

    def filtered(statement: Select) -> Select:
        statement = _scope(statement, start, end, space_id)
        if status:
            statement = statement.where(Message.status == status)
        if feedback == "none":
            statement = statement.where(Message.feedback.is_(None))
        elif feedback:
            statement = statement.where(Message.feedback == feedback)
        if review == "needs_review":
            statement = statement.where(needs_review)
        elif review:
            statement = statement.where(Message.review_status == review)
        if query:
            pattern = (
                "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            statement = statement.where(Message.question.ilike(pattern, escape="\\"))
        return statement

    total = await session.scalar(filtered(_joined(func.count())))
    rows = (
        await session.execute(
            filtered(
                _joined(Message, Space, User)
                .join(Space, Space.id == Conversation.space_id)
                .join(User, User.id == Conversation.user_id)
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return MonitorList(
        total=int(total or 0), items=[MonitorRow(**_row(m, s, u)) for m, s, u in rows]
    )


async def _load(
    session: AsyncSession, message_id: uuid.UUID
) -> tuple[Message, Conversation, Space, User]:
    found = (
        await session.execute(
            select(Message, Conversation, Space, User)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(Space, Space.id == Conversation.space_id)
            .join(User, User.id == Conversation.user_id)
            .where(Message.id == message_id)
        )
    ).first()
    if found is None:
        raise NotFoundError("That answer does not exist.")
    return found[0], found[1], found[2], found[3]


async def detail(session: AsyncSession, message_id: uuid.UUID) -> MonitorDetail:
    message, conversation, space, user = await _load(session, message_id)
    reviewer = await session.get(User, message.reviewed_by) if message.reviewed_by else None
    return MonitorDetail(
        **_row(message, space, user),
        conversation_id=conversation.id,
        standalone_question=message.standalone_question,
        sql=message.sql,
        answer=message.answer,
        assumptions=message.assumptions,
        error=message.error,
        timings=message.timings,
        models=message.models,
        sources=message.sources,
        review_note=message.review_note,
        reviewed_by=reviewer.full_name if reviewer else None,
        reviewed_at=message.reviewed_at,
        feedback_at=message.feedback_at,
    )


async def review(
    session: AsyncSession, message_id: uuid.UUID, admin: User, data: ReviewIn
) -> MonitorDetail:
    message, *_ = await _load(session, message_id)
    message.review_status = data.status
    message.review_note = data.note or None
    message.reviewed_by = admin.id
    message.reviewed_at = datetime.now(UTC)
    await session.commit()
    return await detail(session, message_id)


async def correct(
    session: AsyncSession,
    message_id: uuid.UUID,
    admin: User,
    data: CorrectionIn,
    settings: Settings,
) -> CorrectionOut:
    """Save a verified question and SQL as an example for the answer's space.

    The SQL goes through the guard and is run first, so only a query that works can become an
    example. The review is marked resolved.
    """
    message, _, space, _ = await _load(session, message_id)
    access = SpaceAccess(space, SpaceRole.EDITOR)  # an administrator acts as an editor
    result = await spaces.run_sql(session, access, data.sql, settings)
    example = KnowledgeItem(
        space_id=space.id,
        kind="example_sql",
        title=data.question,
        body=data.sql.strip().rstrip(";").strip(),
        trusted=data.trusted,
        note=data.note,
        created_by=admin.id,
    )
    session.add(example)
    message.review_status = "resolved"
    message.review_note = "Saved as an example." + (" Marked Trusted." if data.trusted else "")
    message.reviewed_by = admin.id
    message.reviewed_at = datetime.now(UTC)
    await session.commit()
    await indexing.items_changed(session, space.id, settings)
    return CorrectionOut(
        example_id=example.id, row_count=result.row_count, detail=await detail(session, message_id)
    )
