"""Account management for admins. There is no public sign-up: admins add people here."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, SettingsDep, require_admin, require_roles
from app.db.models import Role, User
from app.db.session import SessionDep
from app.schemas.auth import InviteCreate, InviteOut, InviteResult, UserCreate, UserOut, UserUpdate
from app.schemas.spaces import UserBrief
from app.services import account_links
from app.services import auth as auth_service

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])

# Names and emails only, for picking space members; admins and editors may use it.
directory_router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_roles(Role.ADMIN, Role.EDITOR))],
)


@directory_router.get("/directory", response_model=list[UserBrief])
async def user_directory(session: SessionDep) -> list[UserBrief]:
    """Active people, to add to a space."""
    users = await session.scalars(
        select(User).where(User.is_active.is_(True)).order_by(func.lower(User.full_name))
    )
    return [UserBrief.model_validate(user) for user in users]


@router.get("", response_model=list[UserOut])
async def list_users(session: SessionDep) -> list[UserOut]:
    return [UserOut.model_validate(user) for user in await auth_service.list_users(session)]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, session: SessionDep, actor: AdminUser) -> UserOut:
    return UserOut.model_validate(await auth_service.create_user(session, body, actor))


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(session: SessionDep) -> list[InviteOut]:
    """Invitations that have been sent and not yet used."""
    return await account_links.pending_invites(session)


@router.post("/invites", response_model=list[InviteResult], status_code=status.HTTP_201_CREATED)
async def send_invites(
    body: InviteCreate, session: SessionDep, actor: AdminUser, settings: SettingsDep
) -> list[InviteResult]:
    """Invite people by email. Each gets a one-time link to choose a password."""
    return await account_links.invite(session, settings, actor, body)


@router.post("/invites/{invite_id}/resend", response_model=InviteResult)
async def resend_invite(
    invite_id: uuid.UUID, session: SessionDep, actor: AdminUser, settings: SettingsDep
) -> InviteResult:
    """A fresh link for a waiting invitation. The old one stops working."""
    return await account_links.resend(session, settings, actor, invite_id)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invite(invite_id: uuid.UUID, session: SessionDep) -> None:
    await account_links.revoke(session, invite_id)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, session: SessionDep, actor: AdminUser
) -> UserOut:
    """Change name, role, or password, or turn the account off/on. Turning it off, or
    setting a new password, signs that person out everywhere."""
    return UserOut.model_validate(await auth_service.update_user(session, user_id, body, actor))
