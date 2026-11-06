"""Spaces, their members, and their data tables (uploaded files and Delta tables).

Access: admins can do everything everywhere. Other people see only the spaces they are
members of; a space's editors manage its data and members, viewers can look. A space you
are not in answers "not found", so its existence isn't revealed.
"""

import functools
import logging
import shutil
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import anyio
from fastapi import UploadFile
from sqlalchemy import func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.db.models import Role, SourceType, Space, SpaceMember, SpaceRole, SpaceTable, User
from app.engine import duckdb_engine
from app.engine.duckdb_engine import FILE_READERS, TableSource
from app.engine.sql_guard import check_query
from app.schemas.spaces import (
    TABLE_NAME,
    ColumnOut,
    DeltaTableCreate,
    MemberOut,
    QueryResultOut,
    SpaceCreate,
    SpaceOut,
    SpaceUpdate,
)
from app.services import notifications
from app.services.access_rules import Restriction, restrictions_for

logger = logging.getLogger(__name__)

# DuckDB work runs in threads; this caps how many run at once.
DUCKDB_SLOTS = anyio.CapacityLimiter(4)
PREVIEW_ROWS = 50


@dataclass(frozen=True, slots=True)
class SpaceAccess:
    space: Space
    role: SpaceRole  # admins count as editors
    user: User | None = None  # who is asking, for what they may read


# ── Access ───────────────────────────────────────────────────────────────────


async def get_access(
    session: AsyncSession, user: User, space_id: uuid.UUID, *, edit: bool = False
) -> SpaceAccess:
    space = await session.get(Space, space_id)
    if space is None:
        raise NotFoundError("That space does not exist.")
    if user.role == Role.ADMIN:
        role = SpaceRole.EDITOR
    else:
        member = await session.get(SpaceMember, (space_id, user.id))
        if member is None:
            raise NotFoundError("That space does not exist.")
        role = SpaceRole(member.role)
    if edit and role != SpaceRole.EDITOR:
        raise ForbiddenError("Only editors of this space can change it.")
    return SpaceAccess(space, role, user)


# ── Spaces ───────────────────────────────────────────────────────────────────


def _counts():
    tables = (
        select(func.count())
        .select_from(SpaceTable)
        .where(SpaceTable.space_id == Space.id)
        .correlate(Space)
        .scalar_subquery()
    )
    members = (
        select(func.count())
        .select_from(SpaceMember)
        .where(SpaceMember.space_id == Space.id)
        .correlate(Space)
        .scalar_subquery()
    )
    return tables, members


def _owner():
    return (
        select(User.full_name).where(User.id == Space.created_by).correlate(Space).scalar_subquery()
    )


def _space_out(space: Space, role: str, tables: int, members: int, owner: str | None) -> SpaceOut:
    return SpaceOut(
        id=space.id,
        name=space.name,
        description=space.description,
        is_personal=space.is_personal,
        tags=list(space.tags or []),
        suggested_questions=list(space.suggested_questions or []),
        owner_name=owner,
        my_role=role,
        table_count=tables,
        member_count=members,
        created_at=space.created_at,
        updated_at=space.updated_at,
    )


async def list_spaces(session: AsyncSession, user: User) -> list[SpaceOut]:
    tables, members = _counts()
    owner = _owner()
    if user.role == Role.ADMIN:
        query = select(Space, literal(SpaceRole.EDITOR.value), tables, members, owner)
    else:
        query = select(Space, SpaceMember.role, tables, members, owner).join(
            SpaceMember, (SpaceMember.space_id == Space.id) & (SpaceMember.user_id == user.id)
        )
    query = query.where(Space.is_personal.is_(False))  # general chats are not listed
    rows = (await session.execute(query.order_by(func.lower(Space.name)))).all()
    return [_space_out(*row) for row in rows]


async def get_space(session: AsyncSession, access: SpaceAccess) -> SpaceOut:
    tables, members = _counts()
    row = (
        await session.execute(select(tables, members, _owner()).where(Space.id == access.space.id))
    ).one()
    return _space_out(access.space, access.role.value, *row)


async def create_space(session: AsyncSession, user: User, data: SpaceCreate) -> SpaceOut:
    if user.role not in (Role.ADMIN, Role.EDITOR):
        raise ForbiddenError("Only admins and editors can create spaces.")
    space = Space(name=data.name, description=data.description, created_by=user.id)
    session.add(space)
    await session.flush()
    session.add(SpaceMember(space_id=space.id, user_id=user.id, role=SpaceRole.EDITOR.value))
    await session.commit()
    return _space_out(space, SpaceRole.EDITOR.value, 0, 1, user.full_name)


async def personal_space(session: AsyncSession, user: User) -> Space:
    """The space behind a person's general chat (no tables); made the first time it is needed."""
    found = await session.scalar(
        select(Space).where(Space.is_personal.is_(True), Space.created_by == user.id)
    )
    if found is not None:
        return found
    space = Space(
        name="General chat",
        description="Your own conversations. Add documents to a chat to ask about them.",
        created_by=user.id,
        is_personal=True,
    )
    session.add(space)
    await session.flush()
    session.add(SpaceMember(space_id=space.id, user_id=user.id, role=SpaceRole.EDITOR.value))
    await session.commit()
    return space


async def update_space(session: AsyncSession, access: SpaceAccess, data: SpaceUpdate) -> SpaceOut:
    if access.space.is_personal:
        raise ForbiddenError("The general chat space can't be changed.")
    if data.name is not None:
        access.space.name = data.name
    if data.description is not None:
        access.space.description = data.description
    if data.tags is not None:
        access.space.tags = data.tags
    if data.suggested_questions is not None:
        access.space.suggested_questions = data.suggested_questions
    await session.commit()
    return await get_space(session, access)


async def delete_space(session: AsyncSession, access: SpaceAccess, settings: Settings) -> None:
    if access.space.is_personal:
        raise ForbiddenError("The general chat space can't be deleted.")
    space_id = access.space.id
    await session.delete(access.space)  # members and tables go with it
    await session.commit()
    # Only uploaded files live here. Delta folders belong to their owners and are never deleted.
    await anyio.to_thread.run_sync(
        functools.partial(shutil.rmtree, space_folder(settings, space_id), ignore_errors=True)
    )


# ── Members ──────────────────────────────────────────────────────────────────


async def list_members(session: AsyncSession, space_id: uuid.UUID) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(SpaceMember, User)
            .join(User, User.id == SpaceMember.user_id)
            .where(SpaceMember.space_id == space_id)
            .order_by(SpaceMember.role, func.lower(User.full_name))
        )
    ).all()
    return [
        MemberOut(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=member.role,
            is_active=user.is_active,
        )
        for member, user in rows
    ]


async def _editor_count(session: AsyncSession, space_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(SpaceMember)
        .where(SpaceMember.space_id == space_id, SpaceMember.role == SpaceRole.EDITOR)
    )


async def set_member(
    session: AsyncSession, access: SpaceAccess, user_id: uuid.UUID, role: str
) -> MemberOut:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("That user does not exist.")
    if not user.is_active:
        raise AppError("That account is turned off.", code="account_disabled")
    member = await session.get(SpaceMember, (access.space.id, user_id))
    added = member is None
    changed = not added and member.role != role
    if member is None:
        member = SpaceMember(space_id=access.space.id, user_id=user_id, role=role)
        session.add(member)
    else:
        if member.role == SpaceRole.EDITOR and role != SpaceRole.EDITOR:
            await _keep_an_editor(session, access.space.id)
        member.role = role
    await session.commit()
    mine = access.user.id if access.user else None
    if (added or changed) and user_id != mine:
        what = "an editor" if role == SpaceRole.EDITOR else "a viewer"
        await notifications.notify(
            session,
            [user_id],
            kind="space_added" if added else "space_role",
            level="info",
            title=(
                f"You were added to {access.space.name}"
                if added
                else f"Your role in {access.space.name} changed"
            ),
            body=f"You are {what} there.",
            link=f"/spaces/{access.space.id}",
        )
    return MemberOut(
        user_id=user.id, full_name=user.full_name, email=user.email, role=role, is_active=True
    )


async def remove_member(session: AsyncSession, access: SpaceAccess, user_id: uuid.UUID) -> None:
    member = await session.get(SpaceMember, (access.space.id, user_id))
    if member is None:
        raise NotFoundError("That person is not a member of this space.")
    if member.role == SpaceRole.EDITOR:
        await _keep_an_editor(session, access.space.id)
    await session.delete(member)
    await session.commit()
    if access.user is None or access.user.id != user_id:
        await notifications.notify(
            session,
            [user_id],
            kind="space_removed",
            level="warning",
            title=f"You were removed from {access.space.name}",
            body="You can no longer open it.",
            link="/spaces",
        )


async def _keep_an_editor(session: AsyncSession, space_id: uuid.UUID) -> None:
    if await _editor_count(session, space_id) <= 1:
        raise ConflictError(
            "A space needs at least one editor. Make someone else an editor first.",
            code="last_editor",
        )


# ── Tables ───────────────────────────────────────────────────────────────────


async def list_tables(session: AsyncSession, space_id: uuid.UUID) -> list[SpaceTable]:
    return list(
        await session.scalars(
            select(SpaceTable).where(SpaceTable.space_id == space_id).order_by(SpaceTable.name)
        )
    )


async def add_upload(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    upload: UploadFile,
    name: str | None,
    settings: Settings,
) -> SpaceTable:
    filename = Path(upload.filename or "upload").name
    extension = Path(filename).suffix.lower()
    if extension not in FILE_READERS:
        kinds = ", ".join(sorted(FILE_READERS))
        raise AppError(f"This file type can't be used. Upload one of: {kinds}.", code="file_type")
    table_name = await _choose_name(session, access.space.id, name, Path(filename).stem)

    table_id = uuid.uuid4()
    target = space_folder(settings, access.space.id) / f"{table_id}.parquet"
    raw = await save_upload(upload, settings.data_path / "tmp", extension, settings.max_upload_mb)
    try:
        await in_thread(duckdb_engine.convert_to_parquet, raw, target)
        source = TableSource(table_name, SourceType.UPLOAD.value, str(target))
        columns, row_count = await in_thread(duckdb_engine.describe, source)
    except BaseException:
        await anyio.Path(target).unlink(missing_ok=True)
        raise
    finally:
        await anyio.Path(raw).unlink(missing_ok=True)

    return await _save_table(
        session,
        SpaceTable(
            id=table_id,
            space_id=access.space.id,
            name=table_name,
            source_type=SourceType.UPLOAD.value,
            source_ref=filename,
            storage_path=str(target),
            columns=[{"name": c.name, "type": c.type} for c in columns],
            row_count=row_count,
            size_bytes=(await anyio.Path(target).stat()).st_size,
            created_by=user.id,
        ),
        cleanup=target,
    )


async def add_delta(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: DeltaTableCreate,
    settings: Settings,
) -> SpaceTable:
    folder = await anyio.to_thread.run_sync(resolve_delta_folder, data.path, settings)
    table_name = await _choose_name(session, access.space.id, data.name, folder.name)
    source = TableSource(table_name, SourceType.DELTA_PATH.value, str(folder))
    columns, row_count = await in_thread(duckdb_engine.describe, source)
    return await _save_table(
        session,
        SpaceTable(
            space_id=access.space.id,
            name=table_name,
            source_type=SourceType.DELTA_PATH.value,
            source_ref=str(folder),
            storage_path=str(folder),
            columns=[{"name": c.name, "type": c.type} for c in columns],
            row_count=row_count,
            delta_version=await anyio.to_thread.run_sync(delta_version, folder),
            created_by=user.id,
        ),
    )


async def delete_table(session: AsyncSession, access: SpaceAccess, table_id: uuid.UUID) -> None:
    table = await get_table(session, access, table_id)
    uploaded = table.source_type == SourceType.UPLOAD.value
    path = Path(table.storage_path)
    await session.delete(table)
    await session.commit()
    if uploaded:  # Delta folders belong to their owners and are never deleted
        await anyio.Path(path).unlink(missing_ok=True)


async def preview_table(
    session: AsyncSession, access: SpaceAccess, table_id: uuid.UUID, settings: Settings
) -> QueryResultOut:
    table = await get_table(session, access, table_id)
    sql = f"SELECT * FROM {duckdb_engine.quote_identifier(table.name)} LIMIT {PREVIEW_ROWS}"
    if table.source_type == SourceType.EXTERNAL.value:
        return await _run_external(
            session, access.space.id, sql, settings, PREVIEW_ROWS, access.user
        )
    rules = await restrictions_for(session, access.space.id, access.user)
    return await _run([table_source(table, rules.get(table.name))], sql, settings, PREVIEW_ROWS)


async def run_sql(
    session: AsyncSession, access: SpaceAccess, sql: str, settings: Settings
) -> QueryResultOut:
    if await has_external_tables(session, access.space.id):
        return await _run_external(
            session, access.space.id, sql, settings, settings.query_max_rows, access.user
        )
    tables = await list_tables(session, access.space.id)
    checked = check_query(sql, {table.name for table in tables})
    rules = await restrictions_for(session, access.space.id, access.user)
    sources = [table_source(t, rules.get(t.name)) for t in tables]
    return await _run(sources, checked, settings, settings.query_max_rows)


# ── Helpers ──────────────────────────────────────────────────────────────────


def space_folder(settings: Settings, space_id: uuid.UUID) -> Path:
    return settings.data_path / "spaces" / str(space_id)


class ExternalTableError(AppError):
    status_code = 409
    code = "external_table"


def table_source(table: SpaceTable, restriction: Restriction | None = None) -> TableSource:
    """The DuckDB source of a file table, as one person may read it (`restriction`: what they may
    not). A table of an external database has none: anything that reaches for one fails here,
    instead of running a file engine on something it can't read."""
    if table.source_type == SourceType.EXTERNAL.value:
        raise ExternalTableError(
            "This table is in an external database, so file features (profiling, value "
            "search) don't apply to it."
        )
    if restriction is None:
        return TableSource(table.name, table.source_type, table.storage_path)
    types = {c["name"]: c["type"] for c in table.columns}
    return TableSource(
        table.name,
        table.source_type,
        table.storage_path,
        hidden=tuple(n for n in types if n in restriction.hidden),
        masked=tuple((n, types[n]) for n in types if n in restriction.masked),
        row_filter=restriction.row_filter,
    )


async def has_external_tables(session: AsyncSession, space_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(SpaceTable)
            .where(
                SpaceTable.space_id == space_id,
                SpaceTable.source_type == SourceType.EXTERNAL.value,
            )
        )
    )


async def ensure_files_only(session: AsyncSession, space_id: uuid.UUID, message: str) -> None:
    """Raise `message` when the space uses an external database (for things that still need the
    file engine)."""
    if await has_external_tables(session, space_id):
        raise ExternalTableError(message)


async def get_table(session: AsyncSession, access: SpaceAccess, table_id: uuid.UUID) -> SpaceTable:
    table = await session.get(SpaceTable, table_id)
    if table is None or table.space_id != access.space.id:
        raise NotFoundError("That table does not exist in this space.")
    return table


async def in_thread(function, *args):
    return await anyio.to_thread.run_sync(function, *args, limiter=DUCKDB_SLOTS)


async def _run_external(
    session: AsyncSession,
    space_id: uuid.UUID,
    sql: str,
    settings: Settings,
    max_rows: int,
    user: User | None = None,
) -> QueryResultOut:
    """The same check-then-run steps as for files, on the space's external database."""
    from app.services import engines  # engines uses this module

    engine = await engines.for_space(session, space_id, settings, user)
    result = await engine.run(
        session,
        engine.check(sql),
        max_rows=max_rows,
        timeout_seconds=settings.query_timeout_seconds,
    )
    return _result_out(result)


async def _run(
    sources: list[TableSource], sql: str, settings: Settings, max_rows: int
) -> QueryResultOut:
    def run() -> duckdb_engine.QueryResult:
        return duckdb_engine.run_query(
            sources, sql, max_rows=max_rows, timeout_seconds=settings.query_timeout_seconds
        )

    return _result_out(await in_thread(run))


def _result_out(result: duckdb_engine.QueryResult) -> QueryResultOut:
    return QueryResultOut(
        columns=[ColumnOut(name=c.name, type=c.type) for c in result.columns],
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
    )


@lru_cache
def _reserved_words() -> frozenset[str]:
    return duckdb_engine.reserved_words()


def suggest_name(text: str) -> str:
    """'Sales 2025 (final).csv' stem -> 'sales_2025_final'."""
    name = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in text.lower())
    name = "_".join(part for part in name.split("_") if part)[:63] or "table"
    if name[0].isdigit():
        name = f"t_{name}"[:63]
    if name in _reserved_words():
        name = f"{name}_data"
    return name


async def _choose_name(
    session: AsyncSession, space_id: uuid.UUID, requested: str | None, fallback: str
) -> str:
    taken = set(
        await session.scalars(select(SpaceTable.name).where(SpaceTable.space_id == space_id))
    )
    if requested:
        requested = requested.strip().lower()
        if not TABLE_NAME.fullmatch(requested) or requested in _reserved_words():
            raise AppError(
                f"'{requested}' can't be used as a table name. Use lowercase letters, digits and "
                "underscores, and avoid SQL words like 'select' or 'order'.",
                code="table_name",
            )
        if requested in taken:
            raise ConflictError(
                f"This space already has a table called '{requested}'.", code="table_name_taken"
            )
        return requested
    base = suggest_name(fallback)
    name, number = base, 2
    while name in taken:
        suffix = f"_{number}"
        name, number = f"{base[: 63 - len(suffix)]}{suffix}", number + 1
    return name


async def save_upload(upload: UploadFile, folder: Path, extension: str, max_mb: int) -> Path:
    await anyio.Path(folder).mkdir(parents=True, exist_ok=True)
    raw = folder / f"{uuid.uuid4().hex}{extension}"
    limit, size = max_mb * 1024 * 1024, 0
    try:
        async with await anyio.open_file(raw, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise AppError(
                        f"The file is larger than the {max_mb} MB limit.",
                        status_code=413,
                        code="file_too_large",
                    )
                await out.write(chunk)
        if size == 0:
            raise AppError("The file is empty.", code="file_empty")
    except BaseException:
        await anyio.Path(raw).unlink(missing_ok=True)
        raise
    return raw


async def _save_table(
    session: AsyncSession, table: SpaceTable, cleanup: Path | None = None
) -> SpaceTable:
    session.add(table)
    try:
        await session.commit()
    except BaseException as exc:
        await session.rollback()
        if cleanup is not None:
            await anyio.Path(cleanup).unlink(missing_ok=True)
        if isinstance(exc, IntegrityError):  # the same name was taken a moment ago
            raise ConflictError(
                f"This space already has a table called '{table.name}'.",
                code="table_name_taken",
            ) from None
        raise
    return table


def resolve_delta_folder(raw: str, settings: Settings) -> Path:
    path = Path(raw.strip().strip('"')).expanduser()
    if not path.is_absolute():
        raise AppError(
            "Give the full folder path, for example C:\\data\\orders_delta.", code="delta_path"
        )
    path = path.resolve()
    roots = settings.allowed_data_roots
    if not any(path.is_relative_to(root) for root in roots):
        raise ForbiddenError(
            "This folder is outside the folders Eye of Ender may read. An admin can add its "
            "parent folder to LOCAL_DATA_ROOTS in .env.",
            code="delta_path_not_allowed",
        )
    if not (path / "_delta_log").is_dir():
        raise AppError(
            "No Delta table was found here: the folder has no _delta_log inside.",
            code="delta_path",
        )
    return path


def delta_version(folder: Path) -> int | None:
    """The newest version number in the table's _delta_log folder."""
    versions = [
        int(entry.stem) for entry in (folder / "_delta_log").glob("*.json") if entry.stem.isdigit()
    ]
    return max(versions) if versions else None
