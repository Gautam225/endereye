"""Invitations and password resets: one-time links sent by email.

An admin invites someone by email and role; the person opens the link, chooses a name and a
password, and is in. Anyone who forgot their password asks for a link of their own. Both work the
same way: a random token is emailed, only its hash is stored, it works once, and it expires.
If the server can't send email, the admin is given the invitation link to pass on by hand.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password, hash_refresh_token, new_refresh_token
from app.db.models import AccountLink, Role, User
from app.schemas.auth import (
    AcceptInvite,
    InviteCreate,
    InviteOut,
    InviteResult,
    LinkPreview,
    ResetRequest,
)
from app.services import auth as auth_service
from app.services import mail_config, mailer, notifications

logger = logging.getLogger(__name__)

INVITE_DAYS = 7
RESET_MINUTES = 60
GONE = "This link has expired or was already used. Ask for a new one."


def _now() -> datetime:
    return datetime.now(UTC)


def _url(settings: Settings, kind: str, token: str) -> str:
    return f"{settings.public_url.rstrip('/')}/{kind}/{token}"


async def _create(
    session: AsyncSession,
    kind: str,
    email: str,
    *,
    ttl: timedelta,
    role: str | None = None,
    user_id: uuid.UUID | None = None,
    actor: User | None = None,
) -> tuple[AccountLink, str]:
    """A new link; any earlier one of the same kind for this address stops working."""
    await session.execute(
        update(AccountLink)
        .where(
            AccountLink.kind == kind,
            AccountLink.email == email,
            AccountLink.used_at.is_(None),
            AccountLink.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    token, token_hash = new_refresh_token()
    link = AccountLink(
        kind=kind,
        email=email,
        role=role,
        user_id=user_id,
        token_hash=token_hash,
        expires_at=_now() + ttl,
        created_by=actor.id if actor else None,
    )
    session.add(link)
    await session.flush()
    return link, token


async def _find_open(session: AsyncSession, token: str, kind: str) -> AccountLink:
    link = await session.scalar(
        select(AccountLink)
        .where(AccountLink.token_hash == hash_refresh_token(token))
        .with_for_update()
    )
    if (
        link is None
        or link.kind != kind
        or link.used_at is not None
        or link.revoked_at is not None
        or link.expires_at <= _now()
    ):
        raise NotFoundError(GONE, code="link_invalid")
    return link


async def _try_send(
    session: AsyncSession, settings: Settings, email: str, subject: str, body: str
) -> str | None:
    """None when the email went out; otherwise a plain reason it did not."""
    if not await mail_config.is_configured(session, settings):
        return "Email is not set up on this server."
    try:
        await mail_config.deliver(session, settings, [email], subject, body, [])
    except mailer.MailError as exc:
        logger.warning("Account email not sent", extra={"error": str(exc)})
        return str(exc)
    return None


def _invite_out(link: AccountLink, invited_by: str | None) -> InviteOut:
    return InviteOut(
        id=link.id,
        email=link.email,
        role=link.role or "viewer",  # type: ignore[arg-type]
        created_at=link.created_at,
        expires_at=link.expires_at,
        invited_by=invited_by,
    )


# ── Invitations (admin) ──────────────────────────────────────────────────────


async def _invite_one(
    session: AsyncSession, settings: Settings, actor: User, email: str, role: str
) -> InviteResult:
    if await session.scalar(select(User.id).where(User.email == email)):
        return InviteResult(
            email=email, outcome="exists", detail="This person already has an account."
        )
    link, token = await _create(
        session, "invite", email, ttl=timedelta(days=INVITE_DAYS), role=role, actor=actor
    )
    url = _url(settings, "invite", token)
    body = (
        f"{actor.full_name} invited you to {settings.app_name} as {role}.\n\n"
        f"Open this link to choose your password and get started:\n{url}\n\n"
        f"The link works once and expires in {INVITE_DAYS} days.\n"
    )
    problem = await _try_send(
        session, settings, email, f"{actor.full_name} invited you to {settings.app_name}", body
    )
    return InviteResult(
        email=email,
        outcome="emailed" if problem is None else "link",
        link=url,
        detail=problem,
        invite=_invite_out(link, actor.full_name),
    )


async def invite(
    session: AsyncSession, settings: Settings, actor: User, data: InviteCreate
) -> list[InviteResult]:
    results: list[InviteResult] = []
    for email in dict.fromkeys(data.emails):  # the same address twice is one invitation
        results.append(await _invite_one(session, settings, actor, email, data.role))
    await session.commit()
    return results


async def pending_invites(session: AsyncSession) -> list[InviteOut]:
    rows = await session.execute(
        select(AccountLink, User.full_name)
        .outerjoin(User, User.id == AccountLink.created_by)
        .where(
            AccountLink.kind == "invite",
            AccountLink.used_at.is_(None),
            AccountLink.revoked_at.is_(None),
            AccountLink.expires_at > _now(),
        )
        .order_by(AccountLink.created_at.desc())
    )
    return [_invite_out(link, name) for link, name in rows]


async def resend(
    session: AsyncSession, settings: Settings, actor: User, invite_id: uuid.UUID
) -> InviteResult:
    """A fresh link for a waiting invitation (the old one stops working)."""
    old = await session.get(AccountLink, invite_id)
    if old is None or old.kind != "invite" or old.used_at is not None or old.revoked_at is not None:
        raise NotFoundError("That invitation is no longer waiting.", code="invite_not_found")
    result = await _invite_one(session, settings, actor, old.email, old.role or "viewer")
    await session.commit()
    return result


async def revoke(session: AsyncSession, invite_id: uuid.UUID) -> None:
    link = await session.get(AccountLink, invite_id)
    if link is None or link.kind != "invite" or link.used_at is not None:
        raise NotFoundError("That invitation is no longer waiting.", code="invite_not_found")
    link.revoked_at = _now()
    await session.commit()


# ── The person opening a link ────────────────────────────────────────────────


async def preview(session: AsyncSession, token: str) -> LinkPreview:
    """What the page shows before asking for a password. Reveals only the link's own address."""
    link = await session.scalar(
        select(AccountLink).where(AccountLink.token_hash == hash_refresh_token(token))
    )
    if (
        link is None
        or link.used_at is not None
        or link.revoked_at is not None
        or link.expires_at <= _now()
    ):
        raise NotFoundError(GONE, code="link_invalid")
    name = None
    if link.kind == "reset" and link.user_id:
        owner = await session.get(User, link.user_id)
        name = owner.full_name if owner else None
    return LinkPreview(
        kind=link.kind,  # type: ignore[arg-type]
        email=link.email,
        role=link.role,  # type: ignore[arg-type]
        full_name=name,
    )


async def accept_invite(
    session: AsyncSession,
    settings: Settings,
    client: auth_service.ClientInfo,
    data: AcceptInvite,
) -> auth_service.IssuedSession:
    link = await _find_open(session, data.token, "invite")
    if await session.scalar(select(User.id).where(User.email == link.email)):
        raise ConflictError(
            "This email already has an account. Sign in instead.", code="email_taken"
        )
    auth_service.check_password_not_email(data.password, link.email)
    user = User(
        email=link.email,
        full_name=data.full_name,
        role=Role(link.role or "viewer"),
        password_hash=await hash_password(data.password),
        last_login_at=_now(),
    )
    session.add(user)
    await session.flush()
    link.used_at = _now()
    await notifications.notify_admins(
        session,
        besides=user.id,
        kind="user_added",
        level="info",
        title=f"{user.full_name} accepted the invitation",
        body=f"They joined as {user.role} ({user.email}).",
        link="/users",
    )
    issued = await auth_service.issue_session(session, user, client, settings)
    await session.commit()
    return issued


# ── Forgot password ──────────────────────────────────────────────────────────


async def forgot(
    session: AsyncSession,
    settings: Settings,
    limits: auth_service.LoginLimits,
    client: auth_service.ClientInfo,
    email: str,
) -> None:
    """Email a reset link if this address has an account. Says nothing either way, so it can't be
    used to find out who has an account, and it is rate-limited so it can't flood an inbox."""
    email_key, ip_key = f"email:{email}", f"ip:{client.ip}"
    if max(limits.by_email.retry_after(email_key), limits.by_ip.retry_after(ip_key)) > 0:
        return
    limits.by_email.hit(email_key)
    limits.by_ip.hit(ip_key)

    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        return
    if settings.sso_issuer and not settings.sso_password_login:
        return  # passwords are off: they sign in with the company account
    link, token = await _create(
        session, "reset", email, ttl=timedelta(minutes=RESET_MINUTES), user_id=user.id
    )
    body = (
        f"Someone asked to reset the password for {user.full_name} on {settings.app_name}.\n\n"
        f"Open this link to choose a new password:\n{_url(settings, 'reset', token)}\n\n"
        f"The link works once and expires in {RESET_MINUTES} minutes. "
        "If this wasn't you, ignore this email: your password stays as it is.\n"
    )
    problem = await _try_send(
        session, settings, email, f"Reset your {settings.app_name} password", body
    )
    if problem:
        link.revoked_at = _now()
    await session.commit()


async def reset_password(
    session: AsyncSession,
    settings: Settings,
    client: auth_service.ClientInfo,
    data: ResetRequest,
) -> auth_service.IssuedSession:
    link = await _find_open(session, data.token, "reset")
    user = await session.get(User, link.user_id) if link.user_id else None
    if user is None or not user.is_active:
        raise NotFoundError(GONE, code="link_invalid")
    auth_service.check_password_not_email(data.password, user.email)
    user.password_hash = await hash_password(data.password)
    link.used_at = _now()
    await auth_service.end_all_sessions(
        session, user
    )  # a stolen session ends with the old password
    user.last_login_at = _now()
    issued = await auth_service.issue_session(session, user, client, settings)
    await session.commit()
    return issued
