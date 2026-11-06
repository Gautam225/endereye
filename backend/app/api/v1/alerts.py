"""Alerts: "tell me when this number goes above that", checked on a schedule. An alert runs as its
owner and is private to them."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.schemas.alerts import AlertCreate, AlertEventOut, AlertOut, AlertUpdate
from app.services import alerts as service
from app.services import spaces

router = APIRouter(prefix="/spaces/{space_id}/alerts", tags=["alerts"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[AlertOut]:
    access = await spaces.get_access(session, user, space_id)
    return await service.list_alerts(session, access, user)


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(
    space_id: uuid.UUID,
    body: AlertCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> AlertOut:
    """Watch a kept answer's number or a shared metric. It is checked once now, so an alert that
    can't read its number is refused with the reason."""
    access = await spaces.get_access(session, user, space_id)
    return await service.create_alert(session, access, user, body, settings)


@router.patch("/{alert_id}", response_model=AlertOut)
async def update_alert(
    space_id: uuid.UUID,
    alert_id: uuid.UUID,
    body: AlertUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> AlertOut:
    access = await spaces.get_access(session, user, space_id)
    alert = await service.get_alert(session, access, user, alert_id)
    return await service.update_alert(session, access, user, alert, body, settings)


@router.delete("/{alert_id}", status_code=NO_CONTENT)
async def delete_alert(
    space_id: uuid.UUID, alert_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    access = await spaces.get_access(session, user, space_id)
    await service.delete_alert(session, await service.get_alert(session, access, user, alert_id))
    return Response(status_code=NO_CONTENT)


@router.post("/{alert_id}/check", response_model=AlertOut)
async def check_now(
    space_id: uuid.UUID,
    alert_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> AlertOut:
    """Look at the number now. People are told only if something changed since the last check."""
    access = await spaces.get_access(session, user, space_id)
    alert = await service.get_alert(session, access, user, alert_id)
    return await service.check_now(session, alert, settings)


@router.get("/{alert_id}/events", response_model=list[AlertEventOut])
async def list_events(
    space_id: uuid.UUID, alert_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[AlertEventOut]:
    access = await spaces.get_access(session, user, space_id)
    alert = await service.get_alert(session, access, user, alert_id)
    return await service.list_events(session, alert)
