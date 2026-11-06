"""Choosing tables of an external database for a space. Administrators only: the connection's
login decides what exists, and an admin decides which of it a space may use."""

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import AdminUser, ClientDep, SettingsDep, require_admin
from app.db.session import SessionDep
from app.schemas.external import ExternalAttach, ExternalAttachOut, RefreshOut, TableFound
from app.services import external_tables
from app.services import spaces as spaces_service

router = APIRouter(tags=["external databases"], dependencies=[Depends(require_admin)])


@router.get("/connections/{connection_id}/schema", response_model=list[TableFound])
async def read_schema(
    connection_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    space_id: uuid.UUID | None = None,
) -> list[TableFound]:
    """The tables and views the connection's login can read, with columns, keys and comments.
    Only the database's catalogs are read, never table rows. Pass `space_id` to see which of
    them that space already uses."""
    return await external_tables.read_schema(session, connection_id, settings, space_id)


@router.post(
    "/spaces/{space_id}/tables/external",
    response_model=ExternalAttachOut,
    status_code=status.HTTP_201_CREATED,
)
async def attach_tables(
    space_id: uuid.UUID,
    body: ExternalAttach,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
) -> ExternalAttachOut:
    """Let the space use these tables. Their columns are read from the database now, and its
    foreign keys become confirmed joins. Nothing is copied."""
    access = await spaces_service.get_access(session, user, space_id, edit=True)
    return await external_tables.attach_tables(session, access, user, body, settings, client)


@router.post("/spaces/{space_id}/tables/external/refresh", response_model=RefreshOut)
async def refresh_tables(
    space_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    user: AdminUser,
    client: ClientDep,
    apply: bool = False,
) -> RefreshOut:
    """Compare the space's tables with the database. Without `apply=true` nothing changes: it
    only reports new, removed and retyped columns, tables that are gone, and foreign-key changes."""
    access = await spaces_service.get_access(session, user, space_id, edit=True)
    return await external_tables.refresh(
        session, access, user, settings, apply=apply, client=client
    )
