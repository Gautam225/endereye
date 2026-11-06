"""Passwords (Argon2id), access tokens (signed JWT), and refresh tokens (random, stored hashed)."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import anyio
import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

_hasher = PasswordHash.recommended()  # Argon2id with current recommended parameters

# Checked when an email is unknown, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"


async def hash_password(password: str) -> str:
    # Argon2 is deliberately slow; run it off the event loop.
    return await anyio.to_thread.run_sync(_hasher.hash, password)


async def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Returns (matches, new_hash). `new_hash` is set when the stored hash should be upgraded."""
    return await anyio.to_thread.run_sync(
        _hasher.verify_and_update, password, password_hash or _DUMMY_HASH
    )


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    token_version: int


def create_access_token(
    user_id: uuid.UUID, token_version: int, settings: Settings
) -> tuple[str, int]:
    """Returns (token, seconds until it expires)."""
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_minutes)
    claims = {
        "sub": str(user_id),
        "ver": token_version,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(claims, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError."""
    claims = jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat", "ver", "type"]},
        leeway=10,
    )
    if claims["type"] != ACCESS_TOKEN_TYPE or not isinstance(claims["ver"], int):
        raise jwt.InvalidTokenError("not an access token")
    try:
        user_id = uuid.UUID(claims["sub"])
    except (ValueError, TypeError) as exc:
        raise jwt.InvalidTokenError("bad subject") from exc
    return AccessClaims(user_id=user_id, token_version=claims["ver"])


def new_refresh_token() -> tuple[str, str]:
    """Returns (token for the cookie, hash for the database). Only the hash is stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    # The token is 256 random bits, so a fast hash is safe here (unlike passwords).
    return hashlib.sha256(token.encode()).hexdigest()
