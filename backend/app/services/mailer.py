"""Sending email through an SMTP account. Which account is decided in `mail_config`: the one an
administrator set up in the app, or else the SMTP_* values in .env. Standard library only: the
send is blocking, so it runs in a thread."""

import asyncio
import mimetypes
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal

from app.core.config import Settings


class MailError(Exception):
    """The email could not be sent. The message is safe to show: it never holds a password."""


@dataclass(frozen=True, slots=True)
class MailConfig:
    host: str = ""
    port: int = 587
    security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str = ""
    password: str = ""
    from_address: str = ""
    timeout: float = 20.0
    source: Literal["app", "env", "none"] = "none"

    def __repr__(self) -> str:  # never print the password
        return f"MailConfig(host={self.host!r}, port={self.port}, source={self.source!r})"

    @classmethod
    def from_settings(cls, settings: Settings) -> "MailConfig":
        """The SMTP_* values of .env."""
        if not settings.smtp_host:
            return cls(timeout=settings.smtp_timeout_seconds)
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            security=settings.smtp_security,
            username=settings.smtp_username,
            password=settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            from_address=settings.smtp_from or settings.smtp_username,
            timeout=settings.smtp_timeout_seconds,
            source="env",
        )


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    content: bytes


def configured(config: MailConfig) -> bool:
    return bool(config.host and config.from_address)


def _single_line(value: str) -> str:
    return " ".join(value.split())  # a header must never contain a line break


def build_message(
    config: MailConfig,
    to: list[str],
    subject: str,
    body: str,
    attachments: list[Attachment],
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = config.from_address
    message["To"] = ", ".join(to)
    message["Subject"] = _single_line(subject)[:200]
    message.set_content(body)
    for attachment in attachments:
        kind, _ = mimetypes.guess_type(attachment.filename)
        maintype, _, subtype = (kind or "application/octet-stream").partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=_single_line(attachment.filename),
        )
    return message


def _send(config: MailConfig, message: EmailMessage) -> None:
    context = ssl.create_default_context()
    try:
        if config.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=config.timeout, context=context
            )
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
        with client:
            if config.security == "starttls":
                client.starttls(context=context)
            if config.username:
                client.login(config.username, config.password)
            client.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise MailError(
            "The mail server refused the sign-in. Check the username and password "
            "(Gmail needs an app password)."
        ) from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError("The mail server refused the recipients.") from None
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(
            f"The mail server could not be reached or refused the message: {exc}"[:300]
        ) from None


async def send(
    config: MailConfig,
    to: list[str],
    subject: str,
    body: str,
    attachments: list[Attachment],
) -> None:
    if not configured(config):
        raise MailError("Email is not set up on this server.")
    message = build_message(config, to, subject, body, attachments)
    await asyncio.to_thread(_send, config, message)
