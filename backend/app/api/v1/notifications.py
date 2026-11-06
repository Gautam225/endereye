"""Pop-up notifications waiting for the signed-in person. The browser asks every few seconds; each
notification is handed over once, then it is theirs to show."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser
from app.db.session import SessionDep
from app.services import notification_prefs
from app.services import notifications as service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    level: Literal["info", "success", "warning", "error"]
    title: str
    body: str
    link: str
    action: dict[str, Any] | None
    quiet_when_here: bool
    created_at: datetime


@router.get("/pending", response_model=list[NotificationOut])
async def pending(user: CurrentUser, session: SessionDep) -> list[NotificationOut]:
    """What has happened since last time, oldest first. Asking again returns only newer ones."""
    return [NotificationOut.model_validate(n) for n in await service.pending(session, user)]


# ── What each person wants to hear about ─────────────────────────────────────


class CategoryOut(BaseModel):
    id: str
    group: str
    title: str
    description: str
    enabled: bool
    client_only: bool  # the browser itself shows these (going offline), so it applies the choice
    admin_only: bool


class PreferencesOut(BaseModel):
    enabled: bool  # the master switch
    paused_until: datetime | None  # set while pop-ups are paused for a while
    categories: list[CategoryOut]


class PreferencesIn(BaseModel):
    enabled: bool | None = None
    paused_until: datetime | None = None
    clear_pause: bool = False
    categories: dict[str, bool] = Field(default_factory=dict, max_length=20)


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    return await notification_prefs.view(session, user)


@router.put("/preferences", response_model=PreferencesOut)
async def set_preferences(
    body: PreferencesIn, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """Change some of the choices; what is left out stays as it is."""
    return await notification_prefs.update(
        session,
        user,
        enabled=body.enabled,
        paused_until=body.paused_until,
        clear_pause=body.clear_pause,
        categories=body.categories,
    )


@router.delete("/preferences", response_model=PreferencesOut)
async def reset_preferences(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Back to the defaults: everything on, nothing paused."""
    return await notification_prefs.reset(session, user)


@router.post("/test", status_code=202)
async def send_test(user: CurrentUser, session: SessionDep) -> dict[str, bool]:
    """Send yourself a pop-up, to see what they look like. It is shown even when paused."""
    sent = await service.notify(
        session,
        [user.id],
        kind="test",
        level="info",
        title="This is a test notification",
        body="If you can read this, pop-ups are working. Click it to open your settings.",
        link="/account?section=notifications",
        force=True,
    )
    return {"sent": sent > 0}
