"""The mail account reports and alerts are sent from. Administrators only: every route requires the
admin role, checked on the server for each request. The password is never sent back."""

from fastapi import APIRouter, Depends

from app.api.deps import AdminUser, SettingsDep, require_admin
from app.db.session import SessionDep
from app.schemas.mail import MailSettingsIn, MailSettingsOut, MailTestIn, MailTestOut
from app.services import mail_config as service

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(require_admin)])


@router.get("", response_model=MailSettingsOut)
async def get_mail_settings(session: SessionDep, settings: SettingsDep) -> MailSettingsOut:
    """Where mail is sent from now: set up here, taken from .env, or not set up."""
    return await service.view(session, settings)


@router.put("", response_model=MailSettingsOut)
async def save_mail_settings(
    body: MailSettingsIn, user: AdminUser, session: SessionDep, settings: SettingsDep
) -> MailSettingsOut:
    """Set the mail account up. It takes effect at once, with no restart."""
    return await service.save(session, settings, user, body)


@router.delete("", response_model=MailSettingsOut)
async def clear_mail_settings(session: SessionDep, settings: SettingsDep) -> MailSettingsOut:
    """Forget the account set up here; SMTP_* in .env (if present) applies again."""
    return await service.clear(session, settings)


@router.post("/test", response_model=MailTestOut)
async def send_test_email(
    body: MailTestIn, user: AdminUser, session: SessionDep, settings: SettingsDep
) -> MailTestOut:
    """Send a test email (to yourself unless `to` is given) to check the settings."""
    return await service.send_test(session, settings, user, str(body.to) if body.to else None)
