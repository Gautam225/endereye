"""Dashboards: a person's own kept answers, refreshed by running their SQL again. Anyone who can
ask questions in the space can keep answers; a dashboard is private to its owner."""

import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.schemas.dashboards import (
    DashboardCreate,
    DashboardOut,
    DashboardUpdate,
    ItemOut,
    ItemUpdate,
    KeptItemsPage,
    PinRequest,
)
from app.services import dashboards as service
from app.services import spaces

router = APIRouter(prefix="/spaces/{space_id}/dashboards", tags=["dashboards"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("", response_model=list[DashboardOut])
async def list_dashboards(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[DashboardOut]:
    access = await spaces.get_access(session, user, space_id)
    return await service.list_dashboards(session, access, user)


@router.post("", response_model=DashboardOut, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    space_id: uuid.UUID, body: DashboardCreate, user: CurrentUser, session: SessionDep
) -> DashboardOut:
    access = await spaces.get_access(session, user, space_id)
    return DashboardOut.model_validate(await service.create_dashboard(session, access, user, body))


@router.post("/pin", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def pin_answer(
    space_id: uuid.UUID,
    body: PinRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ItemOut:
    """Keep an answer from one of your chats on a dashboard."""
    access = await spaces.get_access(session, user, space_id)
    return ItemOut.model_validate(await service.pin(session, access, user, body, settings))


@router.get("/items", response_model=KeptItemsPage)
async def search_items(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> KeptItemsPage:
    """Your kept answers, searchable and paged: for choosing some of them for a report or alert."""
    access = await spaces.get_access(session, user, space_id)
    return await service.search_items(session, access, user, q, limit, offset)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    space_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> ItemOut:
    access = await spaces.get_access(session, user, space_id)
    item = await service.get_item(session, access, user, item_id)
    return ItemOut.model_validate(await service.update_item(session, item, body))


@router.delete("/items/{item_id}", status_code=NO_CONTENT)
async def delete_item(
    space_id: uuid.UUID, item_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    access = await spaces.get_access(session, user, space_id)
    await service.delete_item(session, await service.get_item(session, access, user, item_id))
    return Response(status_code=NO_CONTENT)


@router.post("/items/{item_id}/refresh", response_model=ItemOut)
async def refresh_item(
    space_id: uuid.UUID,
    item_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ItemOut:
    """Run the kept answer's SQL again. If it fails, the old result stays with the reason."""
    access = await spaces.get_access(session, user, space_id)
    item = await service.get_item(session, access, user, item_id)
    return ItemOut.model_validate(await service.refresh_item(session, access, item, settings))


@router.patch("/{dashboard_id}", response_model=DashboardOut)
async def rename_dashboard(
    space_id: uuid.UUID,
    dashboard_id: uuid.UUID,
    body: DashboardUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> DashboardOut:
    access = await spaces.get_access(session, user, space_id)
    dashboard = await service.get_dashboard(session, access, user, dashboard_id)
    return DashboardOut.model_validate(
        await service.rename_dashboard(session, dashboard, body.name)
    )


@router.delete("/{dashboard_id}", status_code=NO_CONTENT)
async def delete_dashboard(
    space_id: uuid.UUID, dashboard_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    access = await spaces.get_access(session, user, space_id)
    await service.delete_dashboard(
        session, await service.get_dashboard(session, access, user, dashboard_id)
    )
    return Response(status_code=NO_CONTENT)


@router.post("/{dashboard_id}/refresh", response_model=list[ItemOut])
async def refresh_dashboard(
    space_id: uuid.UUID,
    dashboard_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> list[ItemOut]:
    """Refresh every kept answer on the dashboard."""
    access = await spaces.get_access(session, user, space_id)
    dashboard = await service.get_dashboard(session, access, user, dashboard_id)
    items = await service.refresh_dashboard(session, access, dashboard, settings)
    return [ItemOut.model_validate(i) for i in items]
