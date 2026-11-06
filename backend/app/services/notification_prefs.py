"""Which pop-ups a person wants. Every kind of notification belongs to one category, and each person
can switch a category off, switch everything off, or pause for a while. Defaults are on, so a new
person (or a new kind of notification) is never silently muted.

Messages about something the person just did (an upload that failed) are not a category here:
they answer an action and always show.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import NotificationPreference, NotificationSettings, Role, User


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    group: str  # how the settings page groups it
    title: str
    description: str
    kinds: tuple[str, ...]  # the notifications it covers
    admin_only: bool = False
    client_only: bool = False  # shown by the browser itself, so the browser applies the choice


CATEGORIES: tuple[Category, ...] = (
    Category(
        "reports",
        "Your work",
        "Reports",
        "When a report is ready to download, fails, or is switched off.",
        ("report_ready", "report_failed", "report_off"),
    ),
    Category(
        "alerts",
        "Your work",
        "Alerts",
        "When one of your alerts goes off, is back to normal, or can't be checked.",
        ("alert_fired", "alert_recovered", "alert_error", "alert_off"),
    ),
    Category(
        "answers",
        "Your work",
        "Chat answers",
        "When an answer finishes while you are on another page.",
        ("answer_ready", "answer_failed"),
    ),
    Category(
        "documents",
        "Your work",
        "Documents",
        "When a document you uploaded is ready, or could not be read.",
        ("document_ready", "document_failed"),
    ),
    Category(
        "sharing",
        "Your work",
        "Shared chats",
        "When someone shares a chat with you.",
        ("chat_shared",),
    ),
    Category(
        "benchmarks",
        "Your work",
        "Benchmarks",
        "When a benchmark run you started finishes.",
        ("benchmark_finished", "benchmark_failed"),
    ),
    Category(
        "access",
        "Access and connection",
        "Spaces and roles",
        "When you are added to or removed from a space, or your role changes.",
        ("space_added", "space_role", "space_removed", "role_changed"),
    ),
    Category(
        "connection",
        "Access and connection",
        "Connection",
        "When you go offline or the server can't be reached.",
        (),
        client_only=True,
    ),
    Category(
        "system",
        "For administrators",
        "System problems",
        "When email, a database connection or the AI service stops working.",
        ("email_problem", "connection_problem", "ai_problem"),
        admin_only=True,
    ),
    Category(
        "people",
        "For administrators",
        "People",
        "When accounts are added, turned off or changed.",
        ("user_added", "user_changed"),
        admin_only=True,
    ),
)

BY_ID = {c.id: c for c in CATEGORIES}
BY_KIND = {kind: c.id for c in CATEGORIES for kind in c.kinds}


def category_of(kind: str) -> str | None:
    """The category a notification belongs to; None for kinds that are always shown."""
    return BY_KIND.get(kind)


def visible_to(user: User) -> list[Category]:
    return [c for c in CATEGORIES if not c.admin_only or user.role == Role.ADMIN]


# ── Reading and changing a person's choices ──────────────────────────────────


async def _settings(session: AsyncSession, user_id: uuid.UUID) -> NotificationSettings | None:
    return await session.get(NotificationSettings, user_id)


async def _choices(session: AsyncSession, user_id: uuid.UUID) -> dict[str, bool]:
    rows = await session.execute(
        select(NotificationPreference.category, NotificationPreference.enabled).where(
            NotificationPreference.user_id == user_id
        )
    )
    return {category: enabled for category, enabled in rows}


def paused(settings: NotificationSettings | None, now: datetime | None = None) -> bool:
    """Turned off, or paused and the time has not come yet."""
    if settings is None:
        return False
    if not settings.enabled:
        return True
    return settings.paused_until is not None and settings.paused_until > (now or datetime.now(UTC))


async def view(session: AsyncSession, user: User) -> dict:
    settings = await _settings(session, user.id)
    choices = await _choices(session, user.id)
    until = settings.paused_until if settings else None
    return {
        "enabled": settings.enabled if settings else True,
        "paused_until": until if until and until > datetime.now(UTC) else None,
        "categories": [
            {
                "id": c.id,
                "group": c.group,
                "title": c.title,
                "description": c.description,
                "enabled": choices.get(c.id, True),
                "client_only": c.client_only,
                "admin_only": c.admin_only,
            }
            for c in visible_to(user)
        ],
    }


async def update(
    session: AsyncSession,
    user: User,
    *,
    enabled: bool | None,
    paused_until: datetime | None,
    clear_pause: bool,
    categories: dict[str, bool],
) -> dict:
    allowed = {c.id for c in visible_to(user)}
    unknown = sorted(set(categories) - allowed)
    if unknown:
        raise AppError(f"Unknown notification type: {', '.join(unknown)}.", code="validation_error")
    if enabled is not None or paused_until is not None or clear_pause:
        settings = await _settings(session, user.id)
        if settings is None:
            settings = NotificationSettings(user_id=user.id)
            session.add(settings)
        if enabled is not None:
            settings.enabled = enabled
        if clear_pause:
            settings.paused_until = None
        elif paused_until is not None:
            if paused_until <= datetime.now(UTC):
                raise AppError("Pause until a time that is still ahead.", code="validation_error")
            settings.paused_until = paused_until
    existing = await _choices(session, user.id)
    for category, wanted in categories.items():
        if wanted and category not in existing:
            continue  # on is the default: nothing to store
        if wanted:
            await session.execute(
                delete(NotificationPreference).where(
                    NotificationPreference.user_id == user.id,
                    NotificationPreference.category == category,
                )
            )
        elif category in existing:
            row = await session.get(NotificationPreference, (user.id, category))
            if row is not None:
                row.enabled = False
        else:
            session.add(NotificationPreference(user_id=user.id, category=category, enabled=False))
    await session.commit()
    return await view(session, user)


async def reset(session: AsyncSession, user: User) -> dict:
    """Everything back to the default: on, not paused."""
    await session.execute(
        delete(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    settings = await _settings(session, user.id)
    if settings is not None:
        await session.delete(settings)
    await session.commit()
    return await view(session, user)


# ── Used when a notification is made ─────────────────────────────────────────


async def who_wants(session: AsyncSession, user_ids: list[uuid.UUID], kind: str) -> list[uuid.UUID]:
    """Of these people, the ones who should hear about this kind of thing."""
    if not user_ids:
        return []
    category = category_of(kind)
    switched_off: set[uuid.UUID] = set(
        await session.scalars(
            select(NotificationSettings.user_id).where(
                NotificationSettings.user_id.in_(user_ids),
                (NotificationSettings.enabled.is_(False))
                | (NotificationSettings.paused_until > datetime.now(UTC)),
            )
        )
    )
    if category is not None:
        switched_off |= set(
            await session.scalars(
                select(NotificationPreference.user_id).where(
                    NotificationPreference.user_id.in_(user_ids),
                    NotificationPreference.category == category,
                    NotificationPreference.enabled.is_(False),
                )
            )
        )
    return [u for u in user_ids if u not in switched_off]
