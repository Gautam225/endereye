"""Notifications: pop-ups for things that happen while a person is in the app.

Whatever happens (a report finishes, an alert fires, a person is added to a space) calls `notify`
with who should hear about it. The browser asks for what is waiting every few seconds and shows
each as a toast, once. Clicking a toast goes to `link`.

Telling someone must never get in the way of the thing itself: `notify` writes in its own
transaction and swallows its own failures.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Notification, Role, User
from app.services import notification_prefs

logger = logging.getLogger(__name__)

Level = Literal["info", "success", "warning", "error"]

WAITING_FOR = timedelta(hours=24)  # a pop-up older than this is no longer news
KEEP_FOR = timedelta(days=7)
DELIVER_AT_ONCE = 10  # per request, so coming back after a weekend is not a wall of pop-ups


async def notify(
    session: AsyncSession,
    user_ids: list[uuid.UUID | None],
    *,
    kind: str,
    level: Level,
    title: str,
    body: str = "",
    link: str = "",
    action: dict[str, Any] | None = None,
    quiet_when_here: bool = False,
    dedupe_key: str | None = None,
    dedupe_minutes: int = 0,
    force: bool = False,
) -> int:
    """Tell each person (people with no id are skipped, and so is anyone who turned this kind off
    or paused their pop-ups, unless `force`). Returns how many were told."""
    people = list(dict.fromkeys(u for u in user_ids if u is not None))
    if not people:
        return 0
    try:
        if session.bind is None:  # a session not made from an engine: nothing to write with
            logger.warning("No database to write a notification to (%s)", kind)
            return 0
        async with AsyncSession(session.bind, expire_on_commit=False) as own:
            if not force:
                people = await notification_prefs.who_wants(own, people, kind)
            told = 0
            for person in people:
                if dedupe_key and dedupe_minutes > 0:
                    recent = await own.scalar(
                        select(Notification.id)
                        .where(
                            Notification.user_id == person,
                            Notification.dedupe_key == dedupe_key,
                            Notification.created_at
                            > datetime.now(UTC) - timedelta(minutes=dedupe_minutes),
                        )
                        .limit(1)
                    )
                    if recent is not None:
                        continue
                own.add(
                    Notification(
                        user_id=person,
                        kind=kind,
                        level=level,
                        title=title[:160],
                        body=body[:400],
                        link=link[:400],
                        action=action,
                        quiet_when_here=quiet_when_here,
                        dedupe_key=dedupe_key,
                    )
                )
                told += 1
            await own.commit()
            return told
    except Exception:
        logger.warning("Could not create a notification (%s)", kind, exc_info=True)
        return 0


async def admin_ids(session: AsyncSession, *, besides: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Every active administrator, optionally without the one who did the thing."""
    ids = list(
        await session.scalars(
            select(User.id).where(User.role == Role.ADMIN, User.is_active.is_(True))
        )
    )
    return [i for i in ids if i != besides]


async def notify_admins(
    session: AsyncSession,
    *,
    besides: uuid.UUID | None = None,
    **fields: Any,
) -> int:
    try:
        return await notify(session, list(await admin_ids(session, besides=besides)), **fields)
    except Exception:
        logger.warning("Could not tell the administrators", exc_info=True)
        return 0


async def pending(session: AsyncSession, user: User) -> list[Notification]:
    """What this person has not seen yet, oldest first. Each is handed over only once."""
    rows = list(
        await session.scalars(
            select(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.delivered_at.is_(None),
                Notification.created_at > datetime.now(UTC) - WAITING_FOR,
            )
            .order_by(Notification.created_at, Notification.id)
            .limit(DELIVER_AT_ONCE)
        )
    )
    if rows:
        await session.execute(
            update(Notification)
            .where(Notification.id.in_([n.id for n in rows]))
            .values(delivered_at=datetime.now(UTC))
        )
        await session.commit()
    return rows


async def prune(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """Forget old notifications, shown or not."""
    async with sessionmaker() as session:
        result = await session.execute(
            delete(Notification).where(Notification.created_at < datetime.now(UTC) - KEEP_FOR)
        )
        await session.commit()
        return result.rowcount or 0


async def email_problem(session: AsyncSession, reason: str) -> int:
    """Email could not be sent: every report and alert is affected, so the administrators are told
    (once every six hours, not once per failed message)."""
    return await notify_admins(
        session,
        kind="email_problem",
        level="error",
        title="Email stopped working",
        body=f"Reports and alerts are not being emailed. {reason}"[:400],
        link="/email?tab=account",
        dedupe_key="email_problem",
        dedupe_minutes=360,
    )
