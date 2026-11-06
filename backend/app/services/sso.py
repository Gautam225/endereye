"""Single sign-on with OpenID Connect (authorization code flow with PKCE).

The browser is sent to the identity provider, signs in there, and comes back with a one-time
code. We swap the code for an ID token, check its signature and claims, and then sign the person
in to this app like any other sign-in. No password is ever seen or stored for SSO accounts.

Nothing about a sign-in in progress is kept on the server: the state, nonce and PKCE secret travel
in a short-lived signed cookie that only the same browser can send back.
"""

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx2
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_password
from app.db.models.user import Role, User
from app.services import auth as auth_service
from app.services import notifications

logger = logging.getLogger(__name__)

STATE_MINUTES = 10
CACHE_SECONDS = 3600
TIMEOUT = 10.0
ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256", "PS384", "PS512"]


class SsoError(Exception):
    """A sign-in that could not be finished. `code` becomes a plain message for the person."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


_provider: tuple[float, Provider] | None = None
_keys: tuple[float, dict[str, Any]] | None = None


def enabled(settings: Settings) -> bool:
    return bool(
        settings.sso_issuer and settings.sso_client_id and settings.sso_client_secret is not None
    )


def redirect_uri(settings: Settings) -> str:
    return f"{settings.public_url.rstrip('/')}/api/v1/auth/sso/callback"


def safe_next(value: str | None) -> str:
    """Only a path inside this app: never another site (an open redirect)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


# ── Talking to the provider ──────────────────────────────────────────────────


async def _get_json(url: str) -> dict[str, Any]:
    try:
        async with httpx2.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except (httpx2.HTTPError, ValueError) as exc:
        logger.warning("SSO provider request failed", extra={"url": url, "error": str(exc)})
        raise SsoError("provider_unreachable") from None
    if not isinstance(data, dict):
        raise SsoError("provider_unreachable")
    return data


async def discover(settings: Settings) -> Provider:
    global _provider
    if _provider and time.monotonic() - _provider[0] < CACHE_SECONDS:
        return _provider[1]
    issuer = settings.sso_issuer.rstrip("/")
    doc = await _get_json(f"{issuer}/.well-known/openid-configuration")
    try:
        found = Provider(
            issuer=str(doc["issuer"]),
            authorization_endpoint=str(doc["authorization_endpoint"]),
            token_endpoint=str(doc["token_endpoint"]),
            jwks_uri=str(doc["jwks_uri"]),
        )
    except KeyError:
        raise SsoError("provider_misconfigured") from None
    _provider = (time.monotonic(), found)
    return found


async def _signing_key(provider: Provider, kid: str | None, *, fresh: bool = False) -> Any:
    global _keys
    if fresh or not _keys or time.monotonic() - _keys[0] > CACHE_SECONDS:
        _keys = (time.monotonic(), await _get_json(provider.jwks_uri))
    for key in jwt.PyJWKSet.from_dict(_keys[1]).keys:
        if kid is None or key.key_id == kid:
            return key.key
    if not fresh:  # the provider may have rotated its keys since we last looked
        return await _signing_key(provider, kid, fresh=True)
    raise SsoError("invalid_token")


# ── Step 1: send the browser to the provider ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class Start:
    url: str
    cookie: str  # signed; set on the browser and checked when it comes back


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def start(settings: Settings, next_path: str | None) -> Start:
    provider = await discover(settings)
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    cookie = jwt.encode(
        {
            "s": state,
            "n": nonce,
            "v": verifier,
            "next": safe_next(next_path),
            "exp": int(time.time()) + STATE_MINUTES * 60,
        },
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.sso_client_id,
            "redirect_uri": redirect_uri(settings),
            "scope": settings.sso_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in provider.authorization_endpoint else "?"
    return Start(f"{provider.authorization_endpoint}{separator}{query}", cookie)


# ── Step 2: the browser comes back ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Finished:
    issued: auth_service.IssuedSession
    next_path: str


async def finish(
    session: AsyncSession,
    settings: Settings,
    client: auth_service.ClientInfo,
    *,
    code: str | None,
    state: str | None,
    cookie: str | None,
) -> Finished:
    if not cookie or not code or not state:
        raise SsoError("expired")
    try:
        saved = jwt.decode(cookie, settings.secret_key.get_secret_value(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise SsoError("expired") from None
    if not secrets.compare_digest(str(saved.get("s", "")), state):
        raise SsoError("expired")

    provider = await discover(settings)
    claims = await _exchange(settings, provider, code, str(saved["v"]), str(saved["n"]))
    user = await _find_or_create(session, settings, provider, claims)
    user.last_login_at = datetime.now(UTC)
    issued = await auth_service.issue_session(session, user, client, settings)
    await session.commit()
    return Finished(issued, safe_next(saved.get("next")))


async def _exchange(
    settings: Settings, provider: Provider, code: str, verifier: str, nonce: str
) -> dict[str, Any]:
    assert settings.sso_client_secret is not None
    try:
        async with httpx2.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                provider.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri(settings),
                    "client_id": settings.sso_client_id,
                    "client_secret": settings.sso_client_secret.get_secret_value(),
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
    except httpx2.HTTPError as exc:
        logger.warning("SSO token request failed", extra={"error": str(exc)})
        raise SsoError("provider_unreachable") from None
    if response.status_code != 200:
        logger.warning("SSO token request refused", extra={"status": response.status_code})
        raise SsoError("rejected")
    try:
        id_token = response.json()["id_token"]
        header = jwt.get_unverified_header(id_token)
        key = await _signing_key(provider, header.get("kid"))
        claims = jwt.decode(
            id_token,
            key,
            algorithms=ID_TOKEN_ALGORITHMS,
            audience=settings.sso_client_id,
            issuer=provider.issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
            leeway=30,
        )
    except SsoError:
        raise
    except (KeyError, ValueError, jwt.InvalidTokenError):
        raise SsoError("invalid_token") from None
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoError("invalid_token")
    return claims


# ── Step 3: who is this? ─────────────────────────────────────────────────────


async def _find_or_create(
    session: AsyncSession, settings: Settings, provider: Provider, claims: dict[str, Any]
) -> User:
    subject = f"{provider.issuer}|{claims['sub']}"[:600]
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if "@" not in email or claims.get("email_verified") is False:
        raise SsoError("no_email")
    domains = {d.lower().lstrip("@") for d in settings.sso_allowed_domains}
    if domains and email.rsplit("@", 1)[1] not in domains:
        raise SsoError("domain_not_allowed")

    user = await session.scalar(select(User).where(User.sso_subject == subject))
    if user is None:
        user = await session.scalar(select(User).where(User.email == email))
        if user is not None:
            user.sso_subject = subject  # an account made by an admin: link it on first sign-in
    if user is not None:
        if not user.is_active:
            raise SsoError("account_disabled")
        return user

    if not settings.sso_auto_create:
        raise SsoError("no_account")
    name = str(claims.get("name") or "").strip() or email.split("@", 1)[0]
    user = User(
        email=email,
        full_name=name[:120],
        # Nobody knows this password, so the account can only be entered through SSO.
        password_hash=await hash_password(secrets.token_urlsafe(48)),
        role=Role(settings.sso_default_role),
        sso_subject=subject,
    )
    session.add(user)
    await session.flush()
    await notifications.notify_admins(
        session,
        besides=user.id,
        kind="user_added",
        level="info",
        title=f"{user.full_name} joined with single sign-on",
        body=f"A new {user.role} account for {user.email}.",
        link="/users",
    )
    return user
