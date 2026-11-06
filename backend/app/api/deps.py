"""Shared route dependencies: settings, the signed-in user, and role checks."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.models import Role, User
from app.db.session import SessionDep
from app.services.auth import ClientInfo

_bearer = HTTPBearer(auto_error=False, description="Access token from /api/v1/auth/login")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_client(request: Request) -> ClientInfo:
    return ClientInfo(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


ClientDep = Annotated[ClientInfo, Depends(get_client)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise UnauthorizedError()
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Your session expired.", code="token_expired") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Please sign in again.", code="invalid_token") from None

    # Loaded on every request, so role changes and deactivation apply immediately.
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise UnauthorizedError(
            "Your session has ended. Please sign in again.", code="session_expired"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], Awaitable[User]]:
    async def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError("You don't have access to this. Ask an admin if you need it.")
        return user

    return check


require_admin = require_roles(Role.ADMIN)
AdminUser = Annotated[User, Depends(require_admin)]
