"""What the AI knows about a space's data: profiles, descriptions, searchable values, joins.

Everyone in the space can read; only editors change anything.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.llm.gateway import LLMDep
from app.schemas.metadata import (
    ColumnMeta,
    ColumnMetaUpdate,
    JoinCreate,
    JoinOut,
    JoinUpdate,
    TableDraft,
    TableMeta,
    TableMetaUpdate,
    ValueMatch,
)
from app.services import indexing, spaces
from app.services import metadata as service

router = APIRouter(prefix="/spaces/{space_id}", tags=["metadata"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("/metadata", response_model=list[TableMeta])
async def get_metadata(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[TableMeta]:
    """Every table with its description, statistics and columns."""
    await spaces.get_access(session, user, space_id)
    return await service.get_metadata(session, space_id)


@router.patch("/tables/{table_id}/metadata", response_model=TableMeta)
async def set_table_description(
    space_id: uuid.UUID,
    table_id: uuid.UUID,
    body: TableMetaUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> TableMeta:
    access = await spaces.get_access(session, user, space_id, edit=True)
    result = await service.set_table_description(session, access, table_id, body.description)
    await indexing.schema_changed(session, space_id, settings)
    return result


@router.post("/tables/{table_id}/profile", response_model=TableMeta)
async def profile_table(
    space_id: uuid.UUID,
    table_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> TableMeta:
    """Read the table again: statistics, searchable values, and Delta changes."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.profile(session, access, table_id, settings)


@router.post("/tables/{table_id}/draft", response_model=TableDraft)
async def draft_descriptions(
    space_id: uuid.UUID,
    table_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
) -> TableDraft:
    """AI-written descriptions and synonyms. Nothing is saved until an editor saves it."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.draft_descriptions(session, access, table_id, llm, settings)


@router.patch("/tables/{table_id}/columns/{column_id}", response_model=ColumnMeta)
async def update_column(
    space_id: uuid.UUID,
    table_id: uuid.UUID,
    column_id: uuid.UUID,
    body: ColumnMetaUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ColumnMeta:
    access = await spaces.get_access(session, user, space_id, edit=True)
    result = await service.update_column(session, access, table_id, column_id, body, settings)
    await indexing.schema_changed(session, space_id, settings)
    return result


@router.get("/values", response_model=list[ValueMatch])
async def search_values(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=127)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[ValueMatch]:
    """Values in the data that look like the text (misspellings and parts of words included)."""
    await spaces.get_access(session, user, space_id)
    return await service.search_values(session, space_id, q.strip(), limit)


@router.get("/joins", response_model=list[JoinOut])
async def list_joins(space_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[JoinOut]:
    await spaces.get_access(session, user, space_id)
    return await service.list_joins(session, space_id)


@router.post("/joins", response_model=JoinOut, status_code=status.HTTP_201_CREATED)
async def create_join(
    space_id: uuid.UUID,
    body: JoinCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> JoinOut:
    access = await spaces.get_access(session, user, space_id, edit=True)
    result = await service.create_join(session, access, body)
    await indexing.schema_changed(session, space_id, settings)
    return result


@router.post("/joins/detect", response_model=list[JoinOut])
async def detect_joins(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> list[JoinOut]:
    """Look for joins between the tables. Returns only the new ones, saved as unconfirmed."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    result = await service.detect_joins(session, access, settings)
    await indexing.schema_changed(session, space_id, settings)
    return result


@router.patch("/joins/{join_id}", response_model=JoinOut)
async def update_join(
    space_id: uuid.UUID,
    join_id: uuid.UUID,
    body: JoinUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> JoinOut:
    access = await spaces.get_access(session, user, space_id, edit=True)
    result = await service.update_join(session, access, join_id, body)
    await indexing.schema_changed(session, space_id, settings)
    return result


@router.delete("/joins/{join_id}", status_code=NO_CONTENT)
async def delete_join(
    space_id: uuid.UUID,
    join_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    access = await spaces.get_access(session, user, space_id, edit=True)
    await service.delete_join(session, access, join_id)
    await indexing.schema_changed(session, space_id, settings)
    return Response(status_code=NO_CONTENT)
