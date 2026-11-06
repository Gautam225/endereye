"""Sign-in, sessions, and accounts.

Sessions: a short-lived access token (JWT, kept in memory by the browser) plus a refresh
token (random, in an httpOnly cookie, stored hashed). Each refresh replaces the refresh
token. If an already-replaced token comes back later, it was copied: the whole session
family is revoked.
"""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.models import RefreshToken, Role, User
from app.schemas.auth import (
    LoginRequest,
    PasswordChange,
    SetupRequest,
    UserCreate,
    UserUpdate,
)
from app.services import notifications

logger = logging.getLogger(__name__)

# Two tabs can refresh at the same moment with the same cookie. A reuse this soon after a
# rotation is that race, not theft: reject it, but keep the session alive.
REFRESH_REUSE_GRACE = timedelta(seconds=30)

# Keys for pg_advisory_xact_lock, so these checks can't race each other.
SETUP_LOCK = 7_301_001
ADMINS_LOCK = 7_301_002


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    access_token: str
    expires_in: int
    refresh_token: str
    token_id: uuid.UUID  # id of the refresh token row
    user: User


@dataclass(frozen=True, slots=True)
class LoginLimits:
    """Failed sign-ins allowed per 15 minutes: 5 per email, 30 per IP address."""

    by_email: SlidingWindowLimiter
    by_ip: SlidingWindowLimiter

    @classmethod
    def default(cls) -> "LoginLimits":
        return cls(SlidingWindowLimiter(5, 15 * 60), SlidingWindowLimiter(30, 15 * 60))


def _now() -> datetime:
    return datetime.now(UTC)


# ── First run ────────────────────────────────────────────────────────────────


async def needs_setup(session: AsyncSession) -> bool:
    return await session.scalar(select(func.count()).select_from(User)) == 0


async def setup_admin(
    session: AsyncSession, data: SetupRequest, client: ClientInfo, settings: Settings
) -> IssuedSession:
    """Create the very first account, as admin. Only possible while there are no users."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETUP_LOCK})
    if not await needs_setup(session):
        raise ConflictError("Setup is already done. Sign in instead.", code="setup_done")
    check_password_not_email(data.password, data.email)
    user = User(
        email=data.email,
        full_name=data.full_name,
        password_hash=await hash_password(data.password),
        role=Role.ADMIN,
        last_login_at=_now(),
    )
    session.add(user)
    await session.flush()
    issued = await issue_session(session, user, client, settings)
    await session.commit()
    logger.info("First admin account created", extra={"user_id": str(user.id)})
    return issued


# ── Sign in, refresh, sign out ───────────────────────────────────────────────


async def login(
    session: AsyncSession,
    data: LoginRequest,
    client: ClientInfo,
    limits: LoginLimits,
    settings: Settings,
) -> IssuedSession:
    if not settings.sso_password_login and settings.sso_issuer:
        raise ForbiddenError(
            "Sign in with your company account instead.", code="password_login_disabled"
        )
    email_key, ip_key = f"email:{data.email}", f"ip:{client.ip}"
    wait = max(limits.by_email.retry_after(email_key), limits.by_ip.retry_after(ip_key))
    if wait > 0:
        minutes = max(1, math.ceil(wait / 60))
        unit = "minute" if minutes == 1 else "minutes"
        raise TooManyRequestsError(
            f"Too many sign-in attempts. Try again in {minutes} {unit}.", retry_after=wait
        )

    user = await session.scalar(select(User).where(User.email == data.email))
    # Always verify, even for unknown emails, so timing doesn't reveal which emails exist.
    matches, upgraded_hash = await verify_password(
        data.password, user.password_hash if user else None
    )
    if user is None or not matches:
        limits.by_email.hit(email_key)
        limits.by_ip.hit(ip_key)
        raise UnauthorizedError("Email or password is incorrect.", code="invalid_credentials")
    if not user.is_active:
        raise ForbiddenError(
            "This account is turned off. Ask an admin to turn it back on.",
            code="account_disabled",
        )

    limits.by_email.reset(email_key)
    if upgraded_hash:
        user.password_hash = upgraded_hash
    user.last_login_at = _now()
    issued = await issue_session(session, user, client, settings)
    await session.commit()
    return issued


async def refresh(
    session: AsyncSession, raw_token: str | None, client: ClientInfo, settings: Settings
) -> IssuedSession:
    ended = UnauthorizedError(
        "Your session has ended. Please sign in again.", code="session_expired"
    )
    if not raw_token:
        raise ended

    # Row lock: two refreshes with the same token are handled one after the other.
    record = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .with_for_update()
    )
    now = _now()
    if record is None:
        raise ended
    if record.revoked_at is not None:
        if record.replaced_by_id is None or not await _family_alive(session, record.family_id):
            raise ended  # signed out, password changed, or session already revoked
        if now - record.revoked_at <= REFRESH_REUSE_GRACE:
            raise UnauthorizedError(
                "This session was just refreshed in another tab.", code="refresh_superseded"
            )
        await _revoke_family(session, record.family_id, now)
        await session.commit()
        logger.warning(
            "A replaced refresh token was used again; that sign-in session is now revoked",
            extra={"user_id": str(record.user_id), "ip": client.ip},
        )
        raise ended
    if record.expires_at <= now:
        raise ended

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        await _revoke_family(session, record.family_id, now)
        await session.commit()
        raise ended

    issued = await issue_session(session, user, client, settings, family_id=record.family_id)
    record.revoked_at = now
    record.replaced_by_id = issued.token_id
    await session.commit()
    return issued


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if record is not None:
        await _revoke_family(session, record.family_id, _now())
        await session.commit()


async def change_password(
    session: AsyncSession,
    user: User,
    data: PasswordChange,
    client: ClientInfo,
    settings: Settings,
) -> IssuedSession:
    """Change your own password. Every other session is signed out; this one continues."""
    matches, _ = await verify_password(data.current_password, user.password_hash)
    if not matches:
        raise AppError("Your current password is not correct.", code="wrong_password")
    if data.new_password == data.current_password:
        raise AppError("Choose a password that is different from the current one.")
    check_password_not_email(data.new_password, user.email)

    user.password_hash = await hash_password(data.new_password)
    await end_all_sessions(session, user)
    issued = await issue_session(session, user, client, settings)
    await session.commit()
    return issued


# ── Accounts (admin) ─────────────────────────────────────────────────────────


async def list_users(session: AsyncSession) -> list[User]:
    return list(await session.scalars(select(User).order_by(User.created_at)))


async def create_user(session: AsyncSession, data: UserCreate, actor: User | None = None) -> User:
    check_password_not_email(data.password, data.email)
    if await session.scalar(select(User.id).where(User.email == data.email)):
        raise ConflictError("A user with this email already exists.", code="email_taken")
    user = User(
        email=data.email,
        full_name=data.full_name,
        role=data.role,
        password_hash=await hash_password(data.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:  # created at the same moment by another request
        await session.rollback()
        raise ConflictError("A user with this email already exists.", code="email_taken") from None
    await notifications.notify_admins(
        session,
        besides=actor.id if actor else None,
        kind="user_added",
        level="info",
        title=f"{user.full_name} was added",
        body=f"A new {user.role} account for {user.email}.",
        link="/users",
    )
    return user


async def update_user(
    session: AsyncSession, user_id: uuid.UUID, data: UserUpdate, actor: User | None = None
) -> User:
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMINS_LOCK})
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("That user does not exist.")

    loses_admin = (
        user.role == Role.ADMIN
        and user.is_active
        and ((data.role is not None and data.role != Role.ADMIN) or data.is_active is False)
    )
    if loses_admin:
        active_admins = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.ADMIN, User.is_active.is_(True))
        )
        if active_admins <= 1:
            raise ConflictError(
                "There must be at least one active admin. Make someone else an admin first.",
                code="last_admin",
            )

    if data.full_name is not None:
        user.full_name = data.full_name
    role_before, active_before = user.role, user.is_active
    if data.role is not None:
        user.role = data.role
    if data.password is not None:
        check_password_not_email(data.password, user.email)
        user.password_hash = await hash_password(data.password)
        await end_all_sessions(session, user)
    if data.is_active is not None and data.is_active != user.is_active:
        user.is_active = data.is_active
        if not data.is_active:
            await end_all_sessions(session, user)
    await session.commit()
    if user.is_active != active_before or user.role != role_before:
        what = (
            "turned off"
            if not user.is_active
            else "turned back on"
            if user.is_active != active_before
            else f"changed to {user.role}"
        )
        await notifications.notify_admins(
            session,
            besides=actor.id if actor else None,
            kind="user_changed",
            level="info",
            title=f"{user.full_name}'s account was {what}"
            if user.is_active != active_before
            else f"{user.full_name}'s role was changed",
            body=user.email if user.is_active != active_before else f"They are now {user.role}.",
            link="/users",
        )
        if user.is_active and user.role != role_before and actor and user.id != actor.id:
            await notifications.notify(
                session,
                [user.id],
                kind="role_changed",
                level="info",
                title="Your role was changed",
                body=f"You are now {user.role}.",
                link="/account",
            )
    return user


# ── Helpers ──────────────────────────────────────────────────────────────────


async def issue_session(
    session: AsyncSession,
    user: User,
    client: ClientInfo,
    settings: Settings,
    *,
    family_id: uuid.UUID | None = None,
) -> IssuedSession:
    token, token_hash = new_refresh_token()
    token_id = uuid.uuid4()
    session.add(
        RefreshToken(
            id=token_id,
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=token_hash,
            expires_at=_now() + timedelta(days=settings.refresh_token_days),
            user_agent=(client.user_agent or "")[:300] or None,
            ip_address=client.ip,
        )
    )
    access_token, expires_in = create_access_token(user.id, user.token_version, settings)
    return IssuedSession(access_token, expires_in, token, token_id, user)


async def _family_alive(session: AsyncSession, family_id: uuid.UUID) -> bool:
    """True while the sign-in session still has a usable (not revoked) token."""
    active = await session.scalar(
        select(RefreshToken.id)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .limit(1)
    )
    return active is not None


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def end_all_sessions(session: AsyncSession, user: User) -> None:
    """Existing access tokens stop working (version bump) and refresh tokens are revoked."""
    user.token_version += 1
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def check_password_not_email(password: str, email: str) -> None:
    if password.strip().lower() in {email, email.split("@")[0]}:
        raise AppError("The password must not be your email address.", code="weak_password")
