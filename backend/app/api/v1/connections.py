"""External database connections. Administrators only: every route here requires the admin role,
checked on the server for each request."""

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import AdminUser, ClientDep, SettingsDep, require_admin
from app.db.models import DbConnection
from app.db.session import SessionDep
from app.schemas.connections import (
    AuditEventOut,
    ConnectionCreate,
    ConnectionOut,
    ConnectionProvision,
    ConnectionTestOut,
    ConnectionUpdate,
    MakeReadOnly,
)
from app.services import connections as service

router = APIRouter(
    prefix="/connections", tags=["connections"], dependencies=[Depends(require_admin)]
)

NO_CONTENT = status.HTTP_204_NO_CONTENT


def _out(connection: DbConnection) -> ConnectionOut:
    return ConnectionOut.model_validate(connection)


def _tested(result: service.ConnectionTestResult) -> ConnectionTestOut:
    return ConnectionTestOut(
        ok=result.check.ok,
        status=result.check.status,
        message=result.check.message,
        server_version=result.check.server_version,
        findings=list(result.check.findings),
        connection=_out(result.connection),
    )


@router.get("", response_model=list[ConnectionOut])
async def list_connections(session: SessionDep) -> list[ConnectionOut]:
    return [_out(c) for c in await service.list_connections(session)]


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
) -> ConnectionOut:
    return _out(await service.create_connection(session, user, body, settings, client))


@router.post("/provision", response_model=ConnectionTestOut, status_code=status.HTTP_201_CREATED)
async def provision_connection(
    body: ConnectionProvision,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
) -> ConnectionTestOut:
    """Connect with a powerful login (like postgres) once, to have a read-only login made. Only
    the new login is saved; the one typed here is used for that and forgotten."""
    result = await service.provision_connection(session, user, body, settings, client)
    return _tested(result)


@router.get("/audit", response_model=list[AuditEventOut])
async def audit_trail(session: SessionDep, limit: int = 100) -> list[AuditEventOut]:
    """Recent changes to connections: who did what and when."""
    return [AuditEventOut.model_validate(e) for e in await service.recent_events(session, limit)]


@router.get("/{connection_id}", response_model=ConnectionOut)
async def get_connection(connection_id: uuid.UUID, session: SessionDep) -> ConnectionOut:
    return _out(await service.get_connection(session, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
) -> ConnectionOut:
    """Change settings. Leave the password out to keep the saved one. Changing the host, port,
    database, user, SSL mode or password marks the connection as untested."""
    return _out(
        await service.update_connection(session, user, connection_id, body, settings, client)
    )


@router.delete("/{connection_id}", status_code=NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, session: SessionDep, user: AdminUser, client: ClientDep
) -> Response:
    await service.delete_connection(session, user, connection_id, client)
    return Response(status_code=NO_CONTENT)


@router.post("/{connection_id}/make-read-only", response_model=ConnectionTestOut)
async def make_read_only(
    connection_id: uuid.UUID,
    body: MakeReadOnly,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
) -> ConnectionTestOut:
    """For a connection blocked because its login can do more than read: use that login once to
    make a read-only one, switch the connection to it, and stop storing the powerful password."""
    result = await service.make_read_only(
        session, user, connection_id, body.schemas, settings, client
    )
    return _tested(result)


@router.post("/{connection_id}/test", response_model=ConnectionTestOut)
async def test_connection(
    connection_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
) -> ConnectionTestOut:
    """Connect, and check that the login can only read. The result is saved on the connection."""
    result = await service.run_connection_test(session, user, connection_id, settings, client)
    return _tested(result)
