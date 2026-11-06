"""Dashboards: a person's kept answers, each refreshed by running its SQL again.

A kept answer stores the question, the SQL and the chart, never a copy of anyone else's view of
the data. Refreshing runs the SQL as the person who owns the dashboard, through the same checks
and access rules as any question, so a tile can't show more than that person may read.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.charts import suggest_chart
from app.chat.pipeline import PREVIEW_ROWS
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.db.models import Dashboard, DashboardItem, MessageStatus, User
from app.schemas.dashboards import (
    DashboardCreate,
    DashboardOut,
    ItemOut,
    ItemUpdate,
    KeptItemsPage,
    KeptItemSummary,
    PinRequest,
)
from app.services import conversations, spaces
from app.services.spaces import SpaceAccess

DEFAULT_NAME = "My dashboard"
MAX_DASHBOARDS = 20


# ── Dashboards ───────────────────────────────────────────────────────────────


async def get_dashboard(
    session: AsyncSession, access: SpaceAccess, user: User, dashboard_id: uuid.UUID
) -> Dashboard:
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.space_id != access.space.id or dashboard.owner_id != user.id:
        raise NotFoundError("That dashboard does not exist.")
    return dashboard


async def _items(session: AsyncSession, dashboard_ids: list[uuid.UUID]) -> list[DashboardItem]:
    return list(
        await session.scalars(
            select(DashboardItem)
            .where(DashboardItem.dashboard_id.in_(dashboard_ids))
            .order_by(DashboardItem.position, DashboardItem.created_at, DashboardItem.id)
        )
    )


async def list_dashboards(
    session: AsyncSession, access: SpaceAccess, user: User
) -> list[DashboardOut]:
    dashboards = list(
        await session.scalars(
            select(Dashboard)
            .where(Dashboard.space_id == access.space.id, Dashboard.owner_id == user.id)
            .order_by(Dashboard.created_at, Dashboard.id)
        )
    )
    by_dashboard: dict[uuid.UUID, list[ItemOut]] = {d.id: [] for d in dashboards}
    if dashboards:
        for item in await _items(session, [d.id for d in dashboards]):
            by_dashboard[item.dashboard_id].append(ItemOut.model_validate(item))
    return [
        DashboardOut.model_validate(d).model_copy(update={"items": by_dashboard[d.id]})
        for d in dashboards
    ]


async def create_dashboard(
    session: AsyncSession, access: SpaceAccess, user: User, data: DashboardCreate
) -> Dashboard:
    count = await session.scalar(
        select(func.count())
        .select_from(Dashboard)
        .where(Dashboard.space_id == access.space.id, Dashboard.owner_id == user.id)
    )
    if count >= MAX_DASHBOARDS:
        raise AppError(
            f"You can have at most {MAX_DASHBOARDS} dashboards in a space.",
            code="too_many_dashboards",
        )
    dashboard = Dashboard(space_id=access.space.id, owner_id=user.id, name=data.name)
    session.add(dashboard)
    await session.commit()
    return dashboard


async def rename_dashboard(session: AsyncSession, dashboard: Dashboard, name: str) -> Dashboard:
    dashboard.name = name
    await session.commit()
    return dashboard


async def delete_dashboard(session: AsyncSession, dashboard: Dashboard) -> None:
    await session.delete(dashboard)
    await session.commit()


# ── Kept answers ─────────────────────────────────────────────────────────────


def _columns_of(result_columns: list[Any]) -> list[dict[str, str]]:
    return [{"name": c.name, "type": c.type} for c in result_columns]


async def pin(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: PinRequest,
    settings: Settings,
) -> DashboardItem:
    """Keep an answer from one of the person's own chats."""
    conversation = await conversations.get_conversation(session, access, user, data.conversation_id)
    message = await conversations.get_message(session, conversation, data.message_id)
    if not message.sql or message.status not in (
        MessageStatus.OK.value,
        MessageStatus.EMPTY.value,
    ):
        raise AppError(
            "Only an answer that came from a query can be kept.", code="validation_error"
        )

    if data.dashboard_id is not None:
        dashboard = await get_dashboard(session, access, user, data.dashboard_id)
    else:
        dashboard = await session.scalar(
            select(Dashboard)
            .where(Dashboard.space_id == access.space.id, Dashboard.owner_id == user.id)
            .order_by(Dashboard.created_at)
            .limit(1)
        )
        if dashboard is None:
            dashboard = await create_dashboard(
                session, access, user, DashboardCreate(name=DEFAULT_NAME)
            )

    held, last = (
        await session.execute(
            select(func.count(), func.max(DashboardItem.position)).where(
                DashboardItem.dashboard_id == dashboard.id
            )
        )
    ).one()
    if held >= settings.dashboard_max_items:
        raise AppError(
            f"A dashboard can hold at most {settings.dashboard_max_items} answers.",
            code="too_many_items",
        )
    chart = message.chart
    title = data.title or str((chart or {}).get("title") or "").strip() or message.question
    item = DashboardItem(
        dashboard_id=dashboard.id,
        title=title[:200],
        question=message.question,
        sql=message.sql,
        chart=chart,
        position=(last + 1) if last is not None else 0,
        columns=message.columns,
        rows=message.rows,
        row_count=message.row_count,
        truncated=message.truncated,
        refreshed_at=message.finished_at or datetime.now(UTC),
    )
    session.add(item)
    await session.commit()
    return item


async def search_items(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    query: str,
    limit: int,
    offset: int,
) -> KeptItemsPage:
    """The person's kept answers in this space, newest first, narrowed by words in the title or
    the question. Paged, so a space with thousands of them is never sent in one go."""
    mine = (Dashboard.space_id == access.space.id) & (Dashboard.owner_id == user.id)
    for word in query.split()[:6]:
        like = f"%{word.replace('%', '').replace('_', '')}%"
        mine &= DashboardItem.title.ilike(like) | DashboardItem.question.ilike(like)
    total = await session.scalar(
        select(func.count())
        .select_from(DashboardItem)
        .join(Dashboard, Dashboard.id == DashboardItem.dashboard_id)
        .where(mine)
    )
    rows = await session.execute(
        select(DashboardItem.id, DashboardItem.title, DashboardItem.question, Dashboard.name)
        .join(Dashboard, Dashboard.id == DashboardItem.dashboard_id)
        .where(mine)
        .order_by(DashboardItem.created_at.desc(), DashboardItem.id)
        .limit(limit)
        .offset(offset)
    )
    return KeptItemsPage(
        total=total or 0,
        items=[KeptItemSummary(id=i, title=t, question=q, dashboard_name=n) for i, t, q, n in rows],
    )


async def get_item(
    session: AsyncSession, access: SpaceAccess, user: User, item_id: uuid.UUID
) -> DashboardItem:
    item = await session.get(DashboardItem, item_id)
    dashboard = await session.get(Dashboard, item.dashboard_id) if item else None
    if (
        item is None
        or dashboard is None
        or dashboard.space_id != access.space.id
        or dashboard.owner_id != user.id
    ):
        raise NotFoundError("That kept answer does not exist.")
    return item


async def update_item(
    session: AsyncSession, item: DashboardItem, data: ItemUpdate
) -> DashboardItem:
    if data.title is not None:
        item.title = data.title
    if data.position is not None:
        item.position = data.position
    await session.commit()
    return item


async def delete_item(session: AsyncSession, item: DashboardItem) -> None:
    await session.delete(item)
    await session.commit()


async def refresh_item(
    session: AsyncSession, access: SpaceAccess, item: DashboardItem, settings: Settings
) -> DashboardItem:
    """Run the SQL again. When it fails the old result stays, with the reason beside it."""
    try:
        result = await spaces.run_sql(session, access, item.sql, settings)
    except AppError as exc:
        item.refresh_error = exc.message[:500]
        await session.commit()
        return item
    columns = _columns_of(result.columns)
    preview = result.rows[:PREVIEW_ROWS]
    item.columns = columns
    item.rows = preview
    item.row_count = result.row_count
    item.truncated = result.truncated
    if item.chart is not None:
        # The numbers moved, so draw it again; the overall figures were of the old data.
        fresh = suggest_chart(columns, preview)
        if fresh is not None and item.chart.get("title"):
            fresh["title"] = item.chart["title"]
        item.chart = fresh
    item.refreshed_at = datetime.now(UTC)
    item.refresh_error = ""
    await session.commit()
    return item


async def refresh_dashboard(
    session: AsyncSession, access: SpaceAccess, dashboard: Dashboard, settings: Settings
) -> list[DashboardItem]:
    items = await _items(session, [dashboard.id])
    return [await refresh_item(session, access, item, settings) for item in items]
