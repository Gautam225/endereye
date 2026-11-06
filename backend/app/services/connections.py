"""Saved connections to external databases: create, change, test, remove.

Every change is written to the audit trail (who, what, when; never a secret). The password is
encrypted on the way in and decrypted only inside `test` (and, in later phases, the query
engine), in memory, for the length of one connection.
"""

import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import AuditEvent, ConnectionStatus, DbConnection, SpaceTable, User
from app.engine import postgres_connect, postgres_provision
from app.schemas.connections import (
    ConnectionCreate,
    ConnectionProvision,
    ConnectionUpdate,
)
from app.services import notifications
from app.services.auth import ClientInfo
from app.services.network_guard import Target, TargetNotAllowedError, check_target

logger = logging.getLogger(__name__)

# Changing any of these means the last test no longer says anything about the connection.
CONNECTION_FIELDS = ("host", "port", "database", "username", "ssl_mode")


def password_context(connection_id: uuid.UUID) -> str:
    """Bound to the row, so an encrypted password copied to another connection won't decrypt."""
    return f"db_connection:{connection_id}"


async def audit_event(
    session: AsyncSession,
    user: User,
    client: ClientInfo | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    target_name: str,
    detail: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_id=user.id,
            actor_name=user.full_name or user.email,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            target_name=target_name,
            detail=detail or {},
            ip=client.ip if client else None,
        )
    )


async def audit(
    session: AsyncSession,
    user: User,
    client: ClientInfo | None,
    action: str,
    connection: DbConnection,
    detail: dict | None = None,
) -> None:
    await audit_event(
        session, user, client, action, "connection", connection.id, connection.name, detail
    )


async def tables_using(session: AsyncSession, connection_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(SpaceTable)
        .where(SpaceTable.connection_id == connection_id)
    )


async def list_connections(session: AsyncSession) -> list[DbConnection]:
    return list(await session.scalars(select(DbConnection).order_by(DbConnection.name)))


async def get_connection(session: AsyncSession, connection_id: uuid.UUID) -> DbConnection:
    connection = await session.get(DbConnection, connection_id)
    if connection is None:
        raise NotFoundError("That connection does not exist.")
    return connection


async def create_connection(
    session: AsyncSession,
    user: User,
    data: ConnectionCreate,
    settings: Settings,
    client: ClientInfo | None = None,
) -> DbConnection:
    vault = settings.vault()  # fails clearly when CONNECTION_ENCRYPTION_KEY is missing
    await check_target(Target(data.host, data.port, data.database), settings, data.ssl_mode)
    connection_id = uuid.uuid4()
    connection = DbConnection(
        id=connection_id,
        name=data.name,
        engine=data.engine,
        host=data.host,
        port=data.port,
        database=data.database,
        username=data.username,
        password_encrypted=vault.encrypt(
            data.password.get_secret_value(), password_context(connection_id)
        ),
        ssl_mode=data.ssl_mode,
        share_results_with_ai=data.share_results_with_ai,
        status=ConnectionStatus.UNTESTED.value,
        status_detail="Not tested yet.",
        created_by=user.id,
    )
    session.add(connection)
    await audit(session, user, client, "connection.created", connection, {"host": data.host})
    await _commit_unique(session)
    return connection


async def update_connection(
    session: AsyncSession,
    user: User,
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
    settings: Settings,
    client: ClientInfo | None = None,
) -> DbConnection:
    connection = await get_connection(session, connection_id)
    changes = data.model_dump(exclude_unset=True, exclude={"password"})
    changed = [name for name, value in changes.items() if value is not None]
    new_password = data.password.get_secret_value() if data.password is not None else None

    in_use = await tables_using(session, connection.id)
    if in_use and any(
        changes.get(name) not in (None, getattr(connection, name))
        for name in ("host", "port", "database")
    ):
        raise ConflictError(
            f"{in_use} table(s) in spaces were taken from this database, so its host, port and "
            "database can't change. Make a new connection instead.",
            code="connection_in_use",
        )
    updated = {
        field: changes.get(field) if changes.get(field) is not None else getattr(connection, field)
        for field in CONNECTION_FIELDS
    }
    if any(changes.get(f) is not None for f in CONNECTION_FIELDS):
        await check_target(
            Target(updated["host"], updated["port"], updated["database"]),
            settings,
            updated["ssl_mode"],
        )
    for name in changed:
        setattr(connection, name, changes[name])
    if new_password is not None:
        connection.password_encrypted = settings.vault().encrypt(
            new_password, password_context(connection.id)
        )
        changed.append("password")
    if any(name in CONNECTION_FIELDS or name == "password" for name in changed):
        connection.status = ConnectionStatus.UNTESTED.value
        connection.status_detail = "Changed since the last test. Test it again."
        connection.tested_at = None
    # Which fields changed, never their values (a password would be one of them).
    await audit(
        session, user, client, "connection.updated", connection, {"changed": sorted(changed)}
    )
    await _commit_unique(session)
    return connection


async def delete_connection(
    session: AsyncSession,
    user: User,
    connection_id: uuid.UUID,
    client: ClientInfo | None = None,
) -> None:
    connection = await get_connection(session, connection_id)
    in_use = await tables_using(session, connection.id)
    if in_use:
        raise ConflictError(
            f"{in_use} table(s) in spaces are taken from this database. Remove them from their "
            "spaces first.",
            code="connection_in_use",
        )
    await audit(session, user, client, "connection.deleted", connection)
    await session.delete(connection)
    await session.commit()


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    connection: DbConnection
    check: postgres_connect.ConnectionCheck


async def run_connection_test(
    session: AsyncSession,
    user: User,
    connection_id: uuid.UUID,
    settings: Settings,
    client: ClientInfo | None = None,
) -> ConnectionTestResult:
    connection = await get_connection(session, connection_id)
    vault = settings.vault()
    password = vault.decrypt(connection.password_encrypted, password_context(connection.id))

    try:
        # Checked again here: DNS answers and settings change after a connection was saved.
        await check_target(
            Target(connection.host, connection.port, connection.database),
            settings,
            connection.ssl_mode,
        )
    except TargetNotAllowedError as exc:
        check = postgres_connect.ConnectionCheck(False, "failed", exc.message)
    else:
        check = await postgres_connect.check_connection(
            postgres_connect.Credentials(
                connection.host,
                connection.port,
                connection.database,
                connection.username,
                password,
                connection.ssl_mode,
            ),
            connect_timeout=settings.external_db_connect_timeout_seconds,
        )

    connection.status = check.status
    connection.status_detail = check.message[:500]
    connection.server_version = check.server_version
    connection.tested_at = datetime.now(UTC)
    if check.ok and vault.needs_rotation(connection.password_encrypted):
        connection.password_encrypted = vault.encrypt(password, password_context(connection.id))
    await audit(
        session,
        user,
        client,
        "connection.tested",
        connection,
        {"status": check.status, "findings": len(check.findings)},
    )
    await session.commit()
    if not check.ok:
        await notifications.notify_admins(
            session,
            kind="connection_problem",
            level="error",
            title=f"{connection.name} is not working",
            body=check.message[:300],
            link="/connections",
            dedupe_key=f"connection:{connection.id}",
            dedupe_minutes=60,
        )
    logger.info(
        "External database connection tested",
        extra={"connection_id": str(connection.id), "status": check.status},
    )
    return ConnectionTestResult(connection, check)


async def recent_events(session: AsyncSession, limit: int = 100) -> list[AuditEvent]:
    return list(
        await session.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500))
        )
    )


async def _commit_unique(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("A connection with that name already exists.") from None


class ConnectionProblemError(AppError):
    """The connection could not be used right now. The message is safe to show."""

    status_code = 502
    code = "connection_problem"


class ConnectionUnsafeError(AppError):
    status_code = 409
    code = "connection_unsafe"


@asynccontextmanager
async def verified_session(
    session: AsyncSession, connection: DbConnection, settings: Settings
) -> AsyncIterator[asyncpg.Connection]:
    """A read-only session on the external database, opened only after every check passes:
    the connection was tested OK, the host is still allowed, and the login is *still* read-only
    (privileges can change after a test). The session is closed when the block ends."""
    if connection.status != ConnectionStatus.OK.value:
        raise ConflictError(
            "Test this connection first. It can be used only after a test shows that it works "
            "and its login is read-only.",
            code="connection_not_tested",
        )
    vault = settings.vault()
    password = vault.decrypt(connection.password_encrypted, password_context(connection.id))
    await check_target(
        Target(connection.host, connection.port, connection.database), settings, connection.ssl_mode
    )
    timeout = settings.external_db_connect_timeout_seconds
    try:
        conn = await postgres_connect.open_connection(
            postgres_connect.Credentials(
                connection.host,
                connection.port,
                connection.database,
                connection.username,
                password,
                connection.ssl_mode,
            ),
            connect_timeout=timeout,
            statement_timeout_seconds=settings.profile_timeout_seconds,
        )
    except Exception as exc:
        _category, message = postgres_connect.safe_error(exc, timeout)
        raise ConnectionProblemError(message) from None
    transaction = conn.transaction(readonly=True)
    try:
        await transaction.start()
        findings = await postgres_connect.role_findings(conn)
        if findings:
            connection.status = ConnectionStatus.UNSAFE.value
            connection.status_detail = "This login can change data; it was blocked."
            await session.commit()
            raise ConnectionUnsafeError(
                "This connection's login is no longer read-only, so it was blocked: "
                + " ".join(findings[:3])
            )
        yield conn
    except asyncpg.PostgresError as exc:
        raise ConnectionProblemError(postgres_connect.safe_error(exc, timeout)[1]) from None
    except (asyncpg.InterfaceError, OSError):
        raise ConnectionProblemError("The connection to the database was lost.") from None
    finally:
        # Nothing is written here, so the transaction is only ended, never committed. The
        # connection may already be gone (Stop terminates it): that is not a new error.
        with contextlib.suppress(Exception):
            await transaction.rollback()
        with contextlib.suppress(Exception):
            await conn.close(timeout=5)


# ── A read-only login, made once with a powerful one ─────────────────────────


async def _make_reader(
    credentials: postgres_connect.Credentials, settings: Settings, schemas: list[str]
) -> postgres_provision.Provisioned:
    """Uses the powerful login once. It is not kept anywhere after this returns."""
    return await postgres_provision.create_reader(
        credentials,
        connect_timeout=settings.external_db_connect_timeout_seconds,
        schemas=schemas or None,
    )


async def provision_connection(
    session: AsyncSession,
    user: User,
    data: ConnectionProvision,
    settings: Settings,
    client: ClientInfo | None = None,
) -> ConnectionTestResult:
    """A new connection whose login is made for it: the admin login typed here is used once to
    create a read-only login, and only that new login is saved."""
    vault = settings.vault()
    await check_target(Target(data.host, data.port, data.database), settings, data.ssl_mode)
    taken = await session.scalar(
        select(func.count()).select_from(DbConnection).where(DbConnection.name == data.name)
    )
    if taken:  # checked before the login is made, so a refusal leaves nothing behind
        raise ConflictError("A connection with that name already exists.")

    made = await _make_reader(
        postgres_connect.Credentials(
            data.host,
            data.port,
            data.database,
            data.admin_username,
            data.admin_password.get_secret_value(),
            data.ssl_mode,
        ),
        settings,
        data.schemas,
    )
    connection_id = uuid.uuid4()
    connection = DbConnection(
        id=connection_id,
        name=data.name,
        engine="postgresql",
        host=data.host,
        port=data.port,
        database=data.database,
        username=made.username,
        password_encrypted=vault.encrypt(made.password, password_context(connection_id)),
        ssl_mode=data.ssl_mode,
        share_results_with_ai=data.share_results_with_ai,
        status=ConnectionStatus.UNTESTED.value,
        status_detail="Not tested yet.",
        created_by=user.id,
    )
    session.add(connection)
    await audit(
        session,
        user,
        client,
        "connection.provisioned",
        connection,
        {"login": made.username, "schemas": list(made.schemas), "tables": made.tables},
    )
    await _commit_unique(session)
    return await run_connection_test(session, user, connection.id, settings, client)


async def make_read_only(
    session: AsyncSession,
    user: User,
    connection_id: uuid.UUID,
    schemas: list[str],
    settings: Settings,
    client: ClientInfo | None = None,
) -> ConnectionTestResult:
    """Replace a blocked connection's login with a read-only one. The saved (powerful) login is
    used once to create it, and its password is replaced, so it is no longer stored."""
    connection = await get_connection(session, connection_id)
    if connection.status != ConnectionStatus.UNSAFE.value:
        raise ConflictError(
            "This connection's login is not blocked for being too powerful. Test it first; "
            "this is only for a login that can do more than read.",
            code="not_unsafe",
        )
    vault = settings.vault()
    old_login = connection.username
    old_password = vault.decrypt(connection.password_encrypted, password_context(connection.id))
    await check_target(
        Target(connection.host, connection.port, connection.database), settings, connection.ssl_mode
    )
    made = await _make_reader(
        postgres_connect.Credentials(
            connection.host,
            connection.port,
            connection.database,
            old_login,
            old_password,
            connection.ssl_mode,
        ),
        settings,
        schemas,
    )
    connection.username = made.username
    connection.password_encrypted = vault.encrypt(made.password, password_context(connection.id))
    connection.status = ConnectionStatus.UNTESTED.value
    connection.status_detail = "Switched to a read-only login. Testing it now."
    connection.tested_at = None
    await audit(
        session,
        user,
        client,
        "connection.made_read_only",
        connection,
        {
            "previous_login": old_login,
            "login": made.username,
            "schemas": list(made.schemas),
            "tables": made.tables,
        },
    )
    await session.commit()
    return await run_connection_test(session, user, connection.id, settings, client)
