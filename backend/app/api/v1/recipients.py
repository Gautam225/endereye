"""A person's saved email addresses, to pick from when sending a report or an alert. Private to
each person."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.schemas.mail import MailStatus, RecipientIn, RecipientOut
from app.services import mail_config as service

router = APIRouter(prefix="/me/recipients", tags=["recipients"])
status_router = APIRouter(prefix="/mail/status", tags=["mail"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@status_router.get("", response_model=MailStatus)
async def mail_status(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> MailStatus:
    """Is email set up? Open to every signed-in person; the details stay with administrators."""
    return await service.status(session, settings)


@router.get("", response_model=list[RecipientOut])
async def list_recipients(user: CurrentUser, session: SessionDep) -> list[RecipientOut]:
    return [RecipientOut.model_validate(r) for r in await service.list_recipients(session, user)]


@router.post("", response_model=RecipientOut, status_code=status.HTTP_201_CREATED)
async def add_recipient(body: RecipientIn, user: CurrentUser, session: SessionDep) -> RecipientOut:
    return RecipientOut.model_validate(await service.add_recipient(session, user, body))


@router.delete("/{recipient_id}", status_code=NO_CONTENT)
async def delete_recipient(
    recipient_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    await service.delete_recipient(session, user, recipient_id)
    return Response(status_code=NO_CONTENT)
