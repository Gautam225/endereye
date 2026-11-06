import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints


def _lowercase(email: str) -> str:
    return email.strip().lower()


def _not_blank(password: str) -> str:
    if not password.strip():
        raise ValueError("must not be only spaces")
    return password


Email = Annotated[EmailStr, AfterValidator(_lowercase)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
# Length is what makes a password strong; 10+ characters, no composition rules.
NewPassword = Annotated[str, Field(min_length=10, max_length=128), AfterValidator(_not_blank)]
AnyPassword = Annotated[str, Field(min_length=1, max_length=128)]
RoleName = Literal["admin", "editor", "viewer"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: RoleName
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class SetupStatus(BaseModel):
    needs_setup: bool


class SetupRequest(BaseModel):
    full_name: FullName
    email: Email
    password: NewPassword


class LoginRequest(BaseModel):
    email: Email
    password: AnyPassword


class SsoStatus(BaseModel):
    """What the sign-in page shows: a company sign-in button, and the password form?"""

    enabled: bool
    name: str
    password_login: bool


class SessionOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds
    user: UserOut


class PasswordChange(BaseModel):
    current_password: AnyPassword
    new_password: NewPassword


class UserCreate(BaseModel):
    full_name: FullName
    email: Email
    role: RoleName = "viewer"
    password: NewPassword


class UserUpdate(BaseModel):
    full_name: FullName | None = None
    role: RoleName | None = None
    is_active: bool | None = None
    password: NewPassword | None = None


# ── Invitations and password resets ──────────────────────────────────────────


class InviteCreate(BaseModel):
    emails: Annotated[list[Email], Field(min_length=1, max_length=50)]
    role: RoleName = "viewer"


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: RoleName
    created_at: datetime
    expires_at: datetime
    invited_by: str | None = None


class InviteResult(BaseModel):
    """What happened to one address. `link` is there so an admin can pass it on by hand."""

    email: str
    outcome: Literal["emailed", "link", "exists"]
    link: str | None = None
    detail: str | None = None
    invite: InviteOut | None = None


class LinkPreview(BaseModel):
    kind: Literal["invite", "reset"]
    email: str
    role: RoleName | None = None
    full_name: str | None = None


class AcceptInvite(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=200)]
    full_name: FullName
    password: NewPassword


class ForgotRequest(BaseModel):
    email: Email


class ResetRequest(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=200)]
    password: NewPassword
