"""Sign-in endpoints. The refresh token travels only in an httpOnly cookie."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import ClientDep, CurrentUser, SettingsDep
from app.core.config import Settings
from app.db.session import SessionDep
from app.schemas.auth import (
    AcceptInvite,
    ForgotRequest,
    LinkPreview,
    LoginRequest,
    PasswordChange,
    ResetRequest,
    SessionOut,
    SetupRequest,
    SetupStatus,
    SsoStatus,
    UserOut,
)
from app.services import account_links
from app.services import auth as auth_service
from app.services import sso as sso_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "eoe_refresh"
# The cookie is sent only to these endpoints, never to the rest of the API.
COOKIE_PATH = "/api/v1/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


# A sign-in in progress with the identity provider. It must come back on the redirect from
# another site, which "strict" would block; it holds nothing a stranger could use.
SSO_COOKIE = "eoe_sso"
SSO_PATH = "/api/v1/auth/sso"


def _set_refresh_cookie(response: Response, issued: auth_service.IssuedSession, settings: Settings):
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_days * 24 * 3600,
        path=COOKIE_PATH,
        httponly=True,  # JavaScript can't read it
        secure=settings.is_production,  # HTTPS only in production
        samesite="strict",  # never sent by other sites
    )


def _session_out(
    response: Response, issued: auth_service.IssuedSession, settings: Settings
) -> SessionOut:
    _set_refresh_cookie(response, issued, settings)
    response.headers["Cache-Control"] = "no-store"
    return SessionOut(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(issued.user),
    )


@router.get("/setup", response_model=SetupStatus)
async def setup_status(session: SessionDep) -> SetupStatus:
    """True until the first account exists."""
    return SetupStatus(needs_setup=await auth_service.needs_setup(session))


@router.post("/setup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def setup(
    body: SetupRequest,
    response: Response,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
) -> SessionOut:
    """Create the first account. It becomes the admin and is signed in."""
    issued = await auth_service.setup_admin(session, body, client, settings)
    return _session_out(response, issued, settings)


@router.post("/login", response_model=SessionOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
) -> SessionOut:
    issued = await auth_service.login(
        session, body, client, request.app.state.login_limits, settings
    )
    return _session_out(response, issued, settings)


@router.post("/refresh", response_model=SessionOut)
async def refresh(
    response: Response,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> SessionOut:
    """New access token from the refresh cookie. The cookie is replaced every time."""
    issued = await auth_service.refresh(session, refresh_token, client, settings)
    return _session_out(response, issued, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep, settings: SettingsDep, refresh_token: RefreshCookie = None
) -> Response:
    await auth_service.logout(session, refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        REFRESH_COOKIE,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
    )
    return response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/password", response_model=SessionOut)
async def change_password(
    body: PasswordChange,
    response: Response,
    user: CurrentUser,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
) -> SessionOut:
    """Change your password. Other devices are signed out; this one gets a fresh session."""
    issued = await auth_service.change_password(session, user, body, client, settings)
    return _session_out(response, issued, settings)


# ── Single sign-on ───────────────────────────────────────────────────────────


@router.get("/sso", response_model=SsoStatus)
async def sso_status(settings: SettingsDep) -> SsoStatus:
    """Whether the sign-in page should show a company sign-in button."""
    on = sso_service.enabled(settings)
    return SsoStatus(
        enabled=on,
        name=settings.sso_name,
        password_login=settings.sso_password_login or not on,
    )


def _sso_failed(settings: Settings, code: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{settings.public_url.rstrip('/')}/login?sso_error={code}", status.HTTP_303_SEE_OTHER
    )
    response.delete_cookie(SSO_COOKIE, path=SSO_PATH)
    return response


@router.get("/sso/start")
async def sso_start(settings: SettingsDep, next: str | None = None) -> RedirectResponse:
    """Send the browser to the company sign-in page."""
    if not sso_service.enabled(settings):
        return _sso_failed(settings, "not_enabled")
    try:
        begun = await sso_service.start(settings, next)
    except sso_service.SsoError as exc:
        return _sso_failed(settings, exc.code)
    response = RedirectResponse(begun.url, status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SSO_COOKIE,
        begun.cookie,
        max_age=sso_service.STATE_MINUTES * 60,
        path=SSO_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/sso/callback")
async def sso_callback(
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    eoe_sso: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """Where the company sign-in page sends the person back. Ends on a page of this app."""
    if not sso_service.enabled(settings):
        return _sso_failed(settings, "not_enabled")
    if error:
        return _sso_failed(settings, "denied" if error == "access_denied" else "rejected")
    try:
        done = await sso_service.finish(
            session, settings, client, code=code, state=state, cookie=eoe_sso
        )
    except sso_service.SsoError as exc:
        return _sso_failed(settings, exc.code)
    # The app signs itself in from the refresh cookie as soon as it opens.
    response = RedirectResponse(
        f"{settings.public_url.rstrip('/')}{done.next_path}", status.HTTP_303_SEE_OTHER
    )
    _set_refresh_cookie(response, done.issued, settings)
    response.delete_cookie(SSO_COOKIE, path=SSO_PATH)
    response.headers["Cache-Control"] = "no-store"
    return response


# ── Invitations and forgotten passwords ──────────────────────────────────────


@router.get("/links/{token}", response_model=LinkPreview)
async def link_preview(token: str, session: SessionDep) -> LinkPreview:
    """What an invitation or reset link is for, before the person chooses a password."""
    return await account_links.preview(session, token)


@router.post("/invite/accept", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    body: AcceptInvite,
    response: Response,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
) -> SessionOut:
    """Join with an invitation: choose a name and password, and be signed in."""
    issued = await account_links.accept_invite(session, settings, client, body)
    return _session_out(response, issued, settings)


@router.post("/forgot", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotRequest,
    request: Request,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
) -> Response:
    """Email a reset link. The answer is the same whether or not the address has an account."""
    await account_links.forgot(
        session, settings, request.app.state.reset_limits, client, body.email
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reset", response_model=SessionOut)
async def reset_password(
    body: ResetRequest,
    response: Response,
    session: SessionDep,
    client: ClientDep,
    settings: SettingsDep,
) -> SessionOut:
    """Choose a new password with a reset link. Every other session is signed out."""
    issued = await account_links.reset_password(session, settings, client, body)
    return _session_out(response, issued, settings)
