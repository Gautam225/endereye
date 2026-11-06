"""Spaces: create them, add members, attach data, and run SQL over it."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ForbiddenError
from app.db.models import Role
from app.db.session import SessionDep
from app.engine.duckdb_engine import FILE_READERS
from app.schemas.spaces import (
    DataLimits,
    DeltaTableCreate,
    MemberOut,
    MemberSet,
    QueryRequest,
    QueryResultOut,
    SpaceCreate,
    SpaceOut,
    SpaceUpdate,
    TableOut,
)
from app.services import indexing
from app.services import metadata as metadata_service
from app.services import spaces as service

router = APIRouter(prefix="/spaces", tags=["spaces"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("", response_model=list[SpaceOut])
async def list_spaces(user: CurrentUser, session: SessionDep) -> list[SpaceOut]:
    """Admins see every space; everyone else sees the spaces they are a member of."""
    return await service.list_spaces(session, user)


@router.get("/limits", response_model=DataLimits)
async def data_limits(_: CurrentUser, settings: SettingsDep) -> DataLimits:
    """What uploads and queries may do, so forms can say so before anything is sent."""
    return DataLimits(
        max_upload_mb=settings.max_upload_mb,
        file_types=sorted(FILE_READERS),
        query_max_rows=settings.query_max_rows,
        query_timeout_seconds=settings.query_timeout_seconds,
    )


@router.post("", response_model=SpaceOut, status_code=status.HTTP_201_CREATED)
async def create_space(body: SpaceCreate, user: CurrentUser, session: SessionDep) -> SpaceOut:
    """Admins and editors can create spaces. The creator becomes the space's editor."""
    return await service.create_space(session, user, body)


@router.get("/{space_id}", response_model=SpaceOut)
async def get_space(space_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> SpaceOut:
    return await service.get_space(session, await service.get_access(session, user, space_id))


@router.patch("/{space_id}", response_model=SpaceOut)
async def update_space(
    space_id: uuid.UUID, body: SpaceUpdate, user: CurrentUser, session: SessionDep
) -> SpaceOut:
    access = await service.get_access(session, user, space_id, edit=True)
    return await service.update_space(session, access, body)


@router.delete("/{space_id}", status_code=NO_CONTENT)
async def delete_space(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Response:
    """Deletes the space and its uploaded files. Delta folders on disk are left alone."""
    access = await service.get_access(session, user, space_id, edit=True)
    await service.delete_space(session, access, settings)
    return Response(status_code=NO_CONTENT)


# ── Members ──────────────────────────────────────────────────────────────────


def _admins_only(user: CurrentUser) -> None:
    if user.role != Role.ADMIN:
        raise ForbiddenError("Only an administrator can change who is in a space or their role.")


@router.get("/{space_id}/members", response_model=list[MemberOut])
async def list_members(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[MemberOut]:
    await service.get_access(session, user, space_id)
    return await service.list_members(session, space_id)


@router.put("/{space_id}/members/{user_id}", response_model=MemberOut)
async def set_member(
    space_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberSet,
    user: CurrentUser,
    session: SessionDep,
) -> MemberOut:
    """Add someone to the space, or change their role in it. Administrators only: a role decides
    what a person may read and change, so it is not something an editor can hand out."""
    _admins_only(user)
    access = await service.get_access(session, user, space_id, edit=True)
    return await service.set_member(session, access, user_id, body.role)


@router.delete("/{space_id}/members/{user_id}", status_code=NO_CONTENT)
async def remove_member(
    space_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    _admins_only(user)
    access = await service.get_access(session, user, space_id, edit=True)
    await service.remove_member(session, access, user_id)
    return Response(status_code=NO_CONTENT)


# ── Tables ───────────────────────────────────────────────────────────────────


@router.get("/{space_id}/tables", response_model=list[TableOut])
async def list_tables(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[TableOut]:
    await service.get_access(session, user, space_id)
    return [TableOut.model_validate(t) for t in await service.list_tables(session, space_id)]


@router.post("/{space_id}/tables/upload", response_model=TableOut, status_code=201)
async def upload_table(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="CSV, TSV, Excel, Parquet, or JSON")],
    name: Annotated[
        str | None, Form(description="Table name; made from the file name if empty")
    ] = None,
) -> TableOut:
    """Upload a file. It is stored as Parquet and becomes a table in the space."""
    access = await service.get_access(session, user, space_id, edit=True)
    table = await service.add_upload(session, access, user, file, name or None, settings)
    await metadata_service.profile_quietly(session, table, settings)
    return TableOut.model_validate(table)


@router.post("/{space_id}/tables/delta", response_model=TableOut, status_code=201)
async def add_delta_table(
    space_id: uuid.UUID,
    body: DeltaTableCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> TableOut:
    """Add a Delta table by its folder on this machine (inside DATA_DIR or LOCAL_DATA_ROOTS)."""
    access = await service.get_access(session, user, space_id, edit=True)
    table = await service.add_delta(session, access, user, body, settings)
    await metadata_service.profile_quietly(session, table, settings)
    return TableOut.model_validate(table)


@router.delete("/{space_id}/tables/{table_id}", status_code=NO_CONTENT)
async def delete_table(
    space_id: uuid.UUID,
    table_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    access = await service.get_access(session, user, space_id, edit=True)
    await service.delete_table(session, access, table_id)
    await indexing.schema_changed(session, space_id, settings)
    return Response(status_code=NO_CONTENT)


@router.get("/{space_id}/tables/{table_id}/preview", response_model=QueryResultOut)
async def preview_table(
    space_id: uuid.UUID,
    table_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> QueryResultOut:
    """The first 50 rows."""
    access = await service.get_access(session, user, space_id)
    return await service.preview_table(session, access, table_id, settings)


@router.post("/{space_id}/query", response_model=QueryResultOut)
async def run_query(
    space_id: uuid.UUID,
    body: QueryRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> QueryResultOut:
    """Run one read-only SELECT over the space's tables (editors; the AI asks for viewers)."""
    access = await service.get_access(session, user, space_id, edit=True)
    return await service.run_sql(session, access, body.sql, settings)
