import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)

SslMode = Literal["disable", "require", "verify-ca", "verify-full"]

IDENTIFIER = re.compile(r"^[A-Za-z0-9_.$-]+$")


def _clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("The name can't be empty.")
    return value


class _ConnectionFields(BaseModel):
    @field_validator("host", "database", "username", check_fields=False)
    @classmethod
    def _no_odd_characters(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value or len(value) > 255:
            raise ValueError("This can't be empty.")
        if any(ch in value for ch in " \t\r\n/\\@?#&=;'\"`<>"):
            raise ValueError("This contains a character that is not allowed.")
        return value


class ConnectionCreate(_ConnectionFields):
    name: str = Field(min_length=1, max_length=80)
    engine: Literal["postgresql"] = "postgresql"
    host: str = Field(max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr = Field(min_length=1, max_length=256)
    ssl_mode: SslMode = "verify-full"
    share_results_with_ai: bool = False

    _name = field_validator("name")(_clean_name)

    @field_validator("database", "username")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value.strip()):
            raise ValueError("Use letters, digits and _ . $ - only.")
        return value.strip()


class ConnectionProvision(_ConnectionFields):
    """Connect with a powerful login ONCE, to have a read-only login made. The admin password is
    used for that and then forgotten: it is never saved."""

    name: str = Field(min_length=1, max_length=80)
    host: str = Field(max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63)
    admin_username: str = Field(min_length=1, max_length=63)
    admin_password: SecretStr = Field(min_length=1, max_length=256)
    ssl_mode: SslMode = "verify-full"
    share_results_with_ai: bool = False
    # The schemas the new login may read. Empty means every non-system schema.
    schemas: list[Annotated[str, StringConstraints(min_length=1, max_length=63)]] = Field(
        default_factory=list, max_length=50
    )

    _name = field_validator("name")(_clean_name)

    @field_validator("database", "admin_username")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value.strip()):
            raise ValueError("Use letters, digits and _ . $ - only.")
        return value.strip()


class MakeReadOnly(BaseModel):
    """Replace the connection's login with a read-only one made for it."""

    schemas: list[Annotated[str, StringConstraints(min_length=1, max_length=63)]] = Field(
        default_factory=list, max_length=50
    )


class ConnectionUpdate(_ConnectionFields):
    """Only the fields that change. A missing password keeps the saved one."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=63)
    username: str | None = Field(default=None, min_length=1, max_length=63)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=256)
    ssl_mode: SslMode | None = None
    share_results_with_ai: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @field_validator("database", "username")
    @classmethod
    def _identifier(cls, value: str | None) -> str | None:
        if value is not None and not IDENTIFIER.fullmatch(value.strip()):
            raise ValueError("Use letters, digits and _ . $ - only.")
        return None if value is None else value.strip()


class ConnectionOut(BaseModel):
    """What the browser sees. There is no password here, not even in encrypted form."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    engine: str
    host: str
    port: int
    database: str
    username: str
    ssl_mode: str
    share_results_with_ai: bool
    status: str
    status_detail: str
    server_version: str | None
    tested_at: datetime | None
    created_at: datetime
    has_password: bool = True


class ConnectionTestOut(BaseModel):
    ok: bool
    status: str
    message: str
    server_version: str | None = None
    findings: list[str] = []
    connection: ConnectionOut


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_name: str
    action: str
    target_type: str
    target_id: str
    target_name: str
    detail: dict
    ip: str | None
