"""Which mail account the app sends from, and each person's saved addresses.

An administrator can set the account up in the app (stored in the database, the password encrypted
with the vault). Until then the SMTP_* values of .env are used, so existing setups keep working.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.vault import VaultError, VaultNotConfiguredError
from app.db.models import MailSettings, SavedRecipient, User
from app.schemas.mail import (
    MailSettingsIn,
    MailSettingsOut,
    MailStatus,
    MailTestOut,
    RecipientIn,
)
from app.services import mailer

logger = logging.getLogger(__name__)

PASSWORD_CONTEXT = "mail-settings"
MAX_SAVED_RECIPIENTS = 100


def _vault_ready(settings: Settings) -> bool:
    try:
        settings.vault()
    except AppError:
        return False
    return True


async def is_configured(session: AsyncSession, settings: Settings) -> bool:
    """Whether mail can be sent at all (an account set up in the app, or SMTP_* in .env)."""
    row = await session.get(MailSettings, 1)
    if row is not None and row.host:
        return True
    return mailer.configured(mailer.MailConfig.from_settings(settings))


async def load(session: AsyncSession, settings: Settings) -> mailer.MailConfig:
    """The account to send from. Raises MailError when the saved password can't be read."""
    row = await session.get(MailSettings, 1)
    if row is None or not row.host:
        return mailer.MailConfig.from_settings(settings)
    password = ""
    if row.password_encrypted:
        try:
            password = settings.vault().decrypt(row.password_encrypted, PASSWORD_CONTEXT)
        except (VaultError, VaultNotConfiguredError):
            raise mailer.MailError(
                "The saved mail password can't be read. Check CONNECTION_ENCRYPTION_KEY, or "
                "save the email settings again."
            ) from None
    return mailer.MailConfig(
        host=row.host,
        port=row.port,
        security=row.security,  # type: ignore[arg-type]
        username=row.username,
        password=password,
        from_address=row.from_address,
        timeout=settings.smtp_timeout_seconds,
        source="app",
    )


async def deliver(
    session: AsyncSession,
    settings: Settings,
    to: list[str],
    subject: str,
    body: str,
    attachments: list[mailer.Attachment],
) -> None:
    """Send an email from the configured account. Raises MailError for any problem."""
    config = await load(session, settings)
    await mailer.send(config, to, subject, body, attachments)


# ── The administrator's page ─────────────────────────────────────────────────


async def status(session: AsyncSession, settings: Settings) -> MailStatus:
    """For everyone: no server details, only whether mail can be sent and from where."""
    row = await session.get(MailSettings, 1)
    if row is not None and row.host:
        return MailStatus(configured=True, from_address=row.from_address)
    env = mailer.MailConfig.from_settings(settings)
    return MailStatus(configured=mailer.configured(env), from_address=env.from_address)


async def view(session: AsyncSession, settings: Settings) -> MailSettingsOut:
    allowed = [d.lower() for d in settings.report_allowed_email_domains]
    row = await session.get(MailSettings, 1)
    if row is not None and row.host:
        who = await session.get(User, row.updated_by) if row.updated_by else None
        return MailSettingsOut(
            configured=True,
            source="app",
            host=row.host,
            port=row.port,
            security=row.security,  # type: ignore[arg-type]
            username=row.username,
            from_address=row.from_address,
            has_password=bool(row.password_encrypted),
            vault_ready=_vault_ready(settings),
            allowed_domains=allowed,
            updated_at=row.updated_at,
            updated_by_name=who.full_name if who else None,
        )
    env = mailer.MailConfig.from_settings(settings)
    return MailSettingsOut(
        configured=mailer.configured(env),
        source="env" if env.host else "none",
        host=env.host,
        port=env.port,
        security=env.security,
        username=env.username,
        from_address=env.from_address,
        has_password=bool(env.password),
        vault_ready=_vault_ready(settings),
        allowed_domains=allowed,
    )


async def save(
    session: AsyncSession, settings: Settings, user: User, data: MailSettingsIn
) -> MailSettingsOut:
    row = await session.get(MailSettings, 1)
    if row is None:
        row = MailSettings(id=1)
        session.add(row)
    row.host = data.host
    row.port = data.port
    row.security = data.security
    row.username = data.username
    row.from_address = str(data.from_address)
    if data.password is not None:
        if data.password == "":
            row.password_encrypted = None
        else:
            try:
                row.password_encrypted = settings.vault().encrypt(data.password, PASSWORD_CONTEXT)
            except VaultNotConfiguredError:
                raise AppError(
                    "To store a mail password, set CONNECTION_ENCRYPTION_KEY in .env first "
                    "(it encrypts saved passwords), then restart the backend.",
                    code="vault_not_configured",
                ) from None
    row.updated_by = user.id
    await session.commit()
    return await view(session, settings)


async def clear(session: AsyncSession, settings: Settings) -> MailSettingsOut:
    """Forget the account set up in the app; the SMTP_* values of .env (if any) apply again."""
    row = await session.get(MailSettings, 1)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return await view(session, settings)


async def send_test(
    session: AsyncSession, settings: Settings, user: User, to: str | None
) -> MailTestOut:
    target = (to or user.email).lower()
    try:
        await deliver(
            session,
            settings,
            [target],
            "Eye of Ender test email",
            "This is a test email from Eye of Ender. If you can read it, reports and alerts "
            "can be emailed from this server.",
            [],
        )
    except mailer.MailError as exc:
        return MailTestOut(ok=False, message=str(exc), sent_to=target)
    return MailTestOut(ok=True, message="The test email was sent.", sent_to=target)


# ── Saved addresses ──────────────────────────────────────────────────────────


async def list_recipients(session: AsyncSession, user: User) -> list[SavedRecipient]:
    return list(
        await session.scalars(
            select(SavedRecipient)
            .where(SavedRecipient.user_id == user.id)
            .order_by(func.lower(SavedRecipient.label), SavedRecipient.email)
        )
    )


async def add_recipient(session: AsyncSession, user: User, data: RecipientIn) -> SavedRecipient:
    held = await session.scalar(
        select(func.count()).select_from(SavedRecipient).where(SavedRecipient.user_id == user.id)
    )
    if held >= MAX_SAVED_RECIPIENTS:
        raise AppError(
            f"You can save at most {MAX_SAVED_RECIPIENTS} addresses.", code="too_many_recipients"
        )
    email = str(data.email).lower()
    item = SavedRecipient(user_id=user.id, email=email, label=data.label)
    session.add(item)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(f"{email} is already in your list.", code="recipient_exists") from None
    return item


async def delete_recipient(session: AsyncSession, user: User, recipient_id: uuid.UUID) -> None:
    item = await session.get(SavedRecipient, recipient_id)
    if item is None or item.user_id != user.id:
        raise NotFoundError("That address is not in your list.")
    await session.delete(item)
    await session.commit()
