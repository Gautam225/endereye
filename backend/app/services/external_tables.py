"""Tables from an external database, used by a space.

What is stored is only descriptions of tables: names, column names and types, comments, and the
foreign keys the database declares. No row is read or copied. Each table's columns are
re-read from the database itself when attached or refreshed, never taken from the browser.

A space uses either files or one external connection, not both, and at most MAX_EXTERNAL_TABLES
tables. Foreign keys become confirmed joins; no join is ever guessed from column names.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.rowcount import UNKNOWN
from app.db.models import (
    DbConnection,
    JoinSource,
    Relationship,
    SourceType,
    SpaceColumn,
    SpaceJoin,
    SpaceTable,
    User,
)
from app.engine.postgres_discovery import TableInfo, discover, to_json
from app.schemas.external import (
    ColumnFound,
    ExternalAttach,
    ExternalAttachOut,
    ForeignKeyFound,
    RefreshOut,
    TableChange,
    TableFound,
    TypeChange,
)
from app.schemas.spaces import TableOut
from app.services import connections, indexing, spaces
from app.services.auth import ClientInfo
from app.services.spaces import SpaceAccess

logger = logging.getLogger(__name__)

MAX_EXTERNAL_TABLES = 50
DESCRIPTION_LENGTH = 1000


async def read_schema(
    session: AsyncSession,
    connection_id: uuid.UUID,
    settings: Settings,
    space_id: uuid.UUID | None = None,
) -> list[TableFound]:
    """What the login can read, for choosing tables. Marks the ones the space already has."""
    connection = await connections.get_connection(session, connection_id)
    async with connections.verified_session(session, connection, settings) as conn:
        found = await discover(conn)
    attached: set[str] = set()
    if space_id is not None:
        attached = {t.source_ref for t in await _external_tables(session, space_id)}
    return [_found(t, t.ref in attached) for t in found]


def _found(table: TableInfo, attached: bool) -> TableFound:
    return TableFound(
        schema_name=table.schema,
        name=table.name,
        kind=table.kind,
        comment=table.comment,
        estimated_rows=table.estimated_rows,
        attached_here=attached,
        columns=[
            ColumnFound(
                name=c.name,
                type=c.type,
                nullable=c.nullable,
                primary_key=c.primary_key,
                comment=c.comment,
            )
            for c in table.columns
        ],
        foreign_keys=[
            ForeignKeyFound(
                name=fk.name,
                columns=list(fk.columns),
                ref_schema=fk.ref_schema,
                ref_table=fk.ref_table,
                ref_columns=list(fk.ref_columns),
                supported=fk.single_column,
            )
            for fk in table.foreign_keys
        ],
    )


async def _external_tables(session: AsyncSession, space_id: uuid.UUID) -> list[SpaceTable]:
    return [
        t
        for t in await spaces.list_tables(session, space_id)
        if t.source_type == SourceType.EXTERNAL.value
    ]


# ── Attach ───────────────────────────────────────────────────────────────────


async def attach_tables(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: ExternalAttach,
    settings: Settings,
    client: ClientInfo | None = None,
) -> ExternalAttachOut:
    space = access.space
    if space.is_personal:
        raise AppError("The general chat has no tables.", code="no_tables_here")
    connection = await connections.get_connection(session, data.connection_id)

    existing = await spaces.list_tables(session, space.id)
    if any(t.source_type != SourceType.EXTERNAL.value for t in existing):
        raise ConflictError(
            "This space has tables from files. A space uses files or one external database, "
            "not both.",
            code="space_has_files",
        )
    if any(t.connection_id != connection.id for t in existing):
        raise ConflictError(
            "This space already uses a different database connection. A space uses one.",
            code="space_other_connection",
        )
    wanted = {(r.schema_name, r.name): r for r in data.tables}
    if len(wanted) != len(data.tables):
        raise AppError("A table was listed twice.", code="duplicate_table")
    if len(existing) + len(wanted) > MAX_EXTERNAL_TABLES:
        raise AppError(
            f"A space can use at most {MAX_EXTERNAL_TABLES} tables. It has {len(existing)}.",
            code="too_many_tables",
        )
    dotted = [f"{s}.{n}" for (s, n) in wanted if "." in s or "." in n]
    if dotted:
        raise AppError(
            "A schema or table name with a dot in it can't be used: " + ", ".join(dotted[:5]),
            code="unsupported_name",
        )
    already = {t.source_ref for t in existing}
    for schema, name in wanted:
        if f"{schema}.{name}" in already:
            raise ConflictError(f'"{schema}"."{name}" is already in this space.', code="attached")

    async with connections.verified_session(session, connection, settings) as conn:
        discovered = await discover(conn)
    by_ref = {(t.schema, t.name): t for t in discovered}
    missing = [f"{s}.{n}" for (s, n) in wanted if (s, n) not in by_ref]
    if missing:
        raise NotFoundError(
            "These were not found, or the database login may not read them: "
            + ", ".join(missing[:10])
        )
    empty = [f"{s}.{n}" for (s, n) in wanted if not by_ref[(s, n)].columns]
    if empty:
        raise AppError(
            "The login can read no columns of: " + ", ".join(empty[:10]), code="no_columns"
        )

    created: list[SpaceTable] = []
    for key, ref in wanted.items():
        info = by_ref[key]
        fallback = info.name if info.schema == "public" else f"{info.schema}_{info.name}"
        name = await spaces._choose_name(session, space.id, ref.alias, fallback)
        table = SpaceTable(
            id=uuid.uuid4(),
            space_id=space.id,
            name=name,
            source_type=SourceType.EXTERNAL.value,
            source_ref=info.ref,
            storage_path="",
            connection_id=connection.id,
            columns=to_json(info.columns),
            row_count=info.estimated_rows if info.estimated_rows else UNKNOWN,
            description=info.comment[:DESCRIPTION_LENGTH],
            profiled_at=datetime.now(UTC),
            created_by=user.id,
        )
        session.add(table)
        await session.flush()
        for column in info.columns:
            session.add(_new_column(table.id, column))
        created.append(table)

    attached_by_ref = {t.source_ref: t for t in [*existing, *created]}
    made, _removed, skipped = await _sync_joins(
        session, space.id, attached_by_ref, {t.ref: t for t in discovered}, remove_missing=False
    )
    await connections.audit_event(
        session,
        user,
        client,
        "space.tables_attached",
        "space",
        space.id,
        space.name,
        {"connection": connection.name, "tables": [t.source_ref for t in created]},
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(
            "One of these tables was added at the same moment. Try again.", code="attached"
        ) from None
    await indexing.schema_changed(session, space.id, settings)
    return ExternalAttachOut(
        tables=[TableOut.model_validate(t) for t in created],
        joins_created=made,
        skipped_foreign_keys=skipped,
    )


def _new_column(table_id: uuid.UUID, column) -> SpaceColumn:
    # Values of an external column are never shown to the AI or indexed unless an admin turns
    # that on for the column: customer data is not for sharing by default.
    return SpaceColumn(
        table_id=table_id,
        name=column.name,
        position=column.position,
        type=column.type,
        description=column.comment[:DESCRIPTION_LENGTH],
        synonyms=[],
        hidden=False,
        share_values=False,
        entity_matching=False,
        indexed_values=0,
        stats=None,
    )


async def _sync_joins(
    session: AsyncSession,
    space_id: uuid.UUID,
    attached: dict[str, SpaceTable],
    discovered: dict[str, TableInfo],
    *,
    remove_missing: bool,
) -> tuple[int, int, list[str]]:
    """Make the space's foreign-key joins match the database. Returns (added, removed, skipped
    keys). Joins an editor made by hand are never touched here."""
    wanted: dict[tuple[uuid.UUID, str, uuid.UUID, str], tuple[str, str]] = {}
    skipped: list[str] = []
    for ref, table in attached.items():
        info = discovered.get(ref)
        if info is None:
            continue
        columns = {c.name: c for c in info.columns}
        for fk in info.foreign_keys:
            parent = attached.get(f"{fk.ref_schema}.{fk.ref_table}")
            if parent is None:
                continue  # the other table is not in this space
            if not fk.single_column:
                skipped.append(f"{ref}: {fk.name}")
                continue
            child_column = columns.get(fk.columns[0])
            parent_info = discovered.get(parent.source_ref)
            parent_columns = {c.name for c in parent_info.columns} if parent_info else set()
            if child_column is None or fk.ref_columns[0] not in parent_columns:
                continue  # one side is not readable by this login
            only_key = child_column.primary_key and sum(c.primary_key for c in info.columns) == 1
            wanted[(table.id, fk.columns[0], parent.id, fk.ref_columns[0])] = (
                Relationship.ONE_TO_ONE.value if only_key else Relationship.MANY_TO_ONE.value,
                fk.name,
            )

    current = {
        (j.left_table_id, j.left_column, j.right_table_id, j.right_column): j
        for j in await session.scalars(select(SpaceJoin).where(SpaceJoin.space_id == space_id))
    }
    added = 0
    for key, (relationship, _name) in wanted.items():
        if key in current:
            continue
        session.add(
            SpaceJoin(
                space_id=space_id,
                left_table_id=key[0],
                left_column=key[1],
                right_table_id=key[2],
                right_column=key[3],
                relationship=relationship,
                source=JoinSource.FOREIGN_KEY.value,
                confirmed=True,
            )
        )
        added += 1
    removed = 0
    if remove_missing:
        for key, join in current.items():
            if join.source == JoinSource.FOREIGN_KEY.value and key not in wanted:
                await session.delete(join)
                removed += 1
    return added, removed, sorted(set(skipped))


# ── Refresh ──────────────────────────────────────────────────────────────────


async def refresh(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    settings: Settings,
    *,
    apply: bool,
    client: ClientInfo | None = None,
) -> RefreshOut:
    """Compare the saved tables with the database. With apply=False nothing is changed, so an
    admin can see what a refresh would do. Tables that are gone (or no longer readable) are
    reported and left in place; they are never deleted by a refresh."""
    tables = await _external_tables(session, access.space.id)
    if not tables:
        raise AppError("This space has no tables from an external database.", code="no_external")
    connection = await session.get(DbConnection, tables[0].connection_id)
    if connection is None:
        raise NotFoundError("The connection of these tables no longer exists.")
    async with connections.verified_session(session, connection, settings) as conn:
        discovered = {t.ref: t for t in await discover(conn)}

    changes: list[TableChange] = []
    for table in tables:
        info = discovered.get(table.source_ref)
        if info is None:
            changes.append(TableChange(name=table.name, ref=table.source_ref, status="missing"))
            continue
        stored = {c["name"]: c["type"] for c in table.columns}
        live = {c.name: c.type for c in info.columns}
        added = [n for n in live if n not in stored]
        removed = [n for n in stored if n not in live]
        retyped = [
            TypeChange(column=n, from_type=stored[n], to_type=live[n])
            for n in live
            if n in stored and stored[n] != live[n]
        ]
        changes.append(
            TableChange(
                name=table.name,
                ref=table.source_ref,
                status="changed" if (added or removed or retyped) else "unchanged",
                added_columns=added,
                removed_columns=removed,
                type_changes=retyped,
            )
        )

    attached = {t.source_ref: t for t in tables}
    if apply:
        await _apply(session, tables, discovered)
    made, removed_joins, skipped = (
        await _sync_joins(session, access.space.id, attached, discovered, remove_missing=True)
        if apply
        else await _count_join_changes(session, access.space.id, attached, discovered)
    )
    if apply:
        await connections.audit_event(
            session,
            user,
            client,
            "space.tables_refreshed",
            "space",
            access.space.id,
            access.space.name,
            {
                "changed": [c.ref for c in changes if c.status == "changed"],
                "missing": [c.ref for c in changes if c.status == "missing"],
            },
        )
        await session.commit()
        await indexing.schema_changed(session, access.space.id, settings)
    return RefreshOut(
        applied=apply,
        tables=changes,
        joins_added=made,
        joins_removed=removed_joins,
        skipped_foreign_keys=skipped,
    )


async def _apply(
    session: AsyncSession, tables: list[SpaceTable], discovered: dict[str, TableInfo]
) -> None:
    for table in tables:
        info = discovered.get(table.source_ref)
        if info is None:
            continue
        existing = {
            c.name: c
            for c in await session.scalars(
                select(SpaceColumn).where(SpaceColumn.table_id == table.id)
            )
        }
        live = {c.name for c in info.columns}
        gone = [n for n in existing if n not in live]
        if gone:
            # Joins that used a column that is gone would be broken: they go with it.
            await session.execute(
                delete(SpaceJoin).where(
                    SpaceJoin.left_table_id == table.id, SpaceJoin.left_column.in_(gone)
                )
            )
            await session.execute(
                delete(SpaceJoin).where(
                    SpaceJoin.right_table_id == table.id, SpaceJoin.right_column.in_(gone)
                )
            )
            for name in gone:
                await session.delete(existing[name])
        for column in info.columns:
            row = existing.get(column.name)
            if row is None:
                session.add(_new_column(table.id, column))
                continue
            row.type, row.position = column.type, column.position
            if not row.description and column.comment:
                row.description = column.comment[:DESCRIPTION_LENGTH]
        table.columns = to_json(info.columns)
        table.row_count = info.estimated_rows if info.estimated_rows else UNKNOWN
        table.profiled_at = datetime.now(UTC)
        if not table.description and info.comment:
            table.description = info.comment[:DESCRIPTION_LENGTH]
    await session.flush()


async def _count_join_changes(
    session: AsyncSession,
    space_id: uuid.UUID,
    attached: dict[str, SpaceTable],
    discovered: dict[str, TableInfo],
) -> tuple[int, int, list[str]]:
    """What a refresh would do to the joins, without doing it."""
    nested = await session.begin_nested()
    try:
        return await _sync_joins(session, space_id, attached, discovered, remove_missing=True)
    finally:
        await nested.rollback()
