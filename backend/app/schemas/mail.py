import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

Host = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Security = Literal["starttls", "ssl", "none"]


class MailSettingsIn(BaseModel):
    host: Host
    port: int = Field(default=587, ge=1, le=65535)
    security: Security = "starttls"
    username: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] = ""
    # Leave out to keep the saved password; send "" to remove it.
    password: Annotated[str, StringConstraints(max_length=500)] | None = None
    from_address: EmailStr


class MailSettingsOut(BaseModel):
    configured: bool
    source: Literal["app", "env", "none"]  # set up in the app, taken from .env, or not set up
    host: str
    port: int
    security: Security
    username: str
    from_address: str
    has_password: bool
    vault_ready: bool  # a password can be stored (CONNECTION_ENCRYPTION_KEY is set)
    allowed_domains: list[str]
    updated_at: datetime | None = None
    updated_by_name: str | None = None


class MailStatus(BaseModel):
    """What anyone may know about email: whether it works, and the address it is sent from."""

    configured: bool
    from_address: str


class MailTestIn(BaseModel):
    to: EmailStr | None = None  # leave out to send it to yourself


class MailTestOut(BaseModel):
    ok: bool
    message: str
    sent_to: str


class RecipientIn(BaseModel):
    email: EmailStr
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    label: str
    created_at: datetime
