"""What the AI knows about a space's data: profiles, descriptions, searchable values, joins.

Everything here is stored per space and never changes the data itself. Hiding a column only
removes it from what the AI is shown; permissions are not affected.
"""

import functools
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import anyio
from sqlalchemy import delete, desc, func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    ColumnValue,
    JoinSource,
    SourceType,
    SpaceColumn,
    SpaceJoin,
    SpaceTable,
)
from app.engine import duckdb_engine, profiling
from app.engine.duckdb_engine import Column
from app.engine.profiling import JoinTable
from app.llm.gateway import LLMGateway
from app.schemas.metadata import (
    ColumnDraft,
    ColumnMeta,
    ColumnMetaUpdate,
    JoinCreate,
    JoinOut,
    JoinUpdate,
    TableDraft,
    TableMeta,
    ValueMatch,
    clean_synonyms,
)
from app.services import indexing, spaces
from app.services.spaces import SpaceAccess

logger = logging.getLogger(__name__)

DRAFT_MAX_COLUMNS = 60  # one AI request describes at most this many columns of a table
DRAFT_DESCRIPTION_LENGTH = 250
DRAFT_SYNONYMS = 5


# ── Profiling ────────────────────────────────────────────────────────────────


async def profile(
    session: AsyncSession, access: SpaceAccess, table_id: uuid.UUID, settings: Settings
) -> TableMeta:
    """(Re)read a table: its columns, statistics and searchable values.

    Descriptions, synonyms and switches an editor has set are kept; columns that no longer
    exist are dropped.
    """
    table = await spaces.get_table(session, access, table_id)
    await profile_table(session, table, settings)
    return await _table_meta(session, table)


async def profile_table(session: AsyncSession, table: SpaceTable, settings: Settings) -> None:
    source = spaces.table_source(table)
    timeout = settings.profile_timeout_seconds
    found, _ = await spaces.in_thread(duckdb_engine.describe, source)
    result = await spaces.in_thread(
        functools.partial(profiling.profile_table, source, found, timeout_seconds=timeout)
    )

    existing = {c.name: c for c in await _columns(session, table.id)}
    in_use = await _entity_columns_elsewhere(session, table)
    stats = {c.name: c for c in result.columns}
    keep = {c.name for c in found}
    for name, column in existing.items():
        if name not in keep:
            await session.delete(column)

    for position, field in enumerate(found):
        column = existing.get(field.name)
        profiled = stats[field.name]
        if column is None:
            column = SpaceColumn(
                table_id=table.id,
                name=field.name,
                synonyms=[],
                description="",
                hidden=False,
                share_values=True,
                entity_matching=False,
                indexed_values=0,
            )
            if profiled.stats["searchable"] and in_use < profiling.VALUE_INDEX_MAX_COLUMNS:
                column.entity_matching = True
                in_use += 1
            session.add(column)
        column.type, column.position, column.stats = field.type, position, profiled.stats
        await session.flush()
        await _store_values(session, column, profiled.values)

    table.columns = [{"name": c.name, "type": c.type} for c in found]
    table.row_count = result.row_count
    table.profiled_at = datetime.now(UTC)
    if table.source_type == SourceType.DELTA_PATH.value:
        table.delta_version = await anyio.to_thread.run_sync(
            spaces.delta_version, Path(table.storage_path)
        )
    await session.commit()
    await indexing.schema_changed(session, table.space_id, settings)


async def profile_quietly(session: AsyncSession, table: SpaceTable, settings: Settings) -> None:
    """Profile a new table. If that fails the table is still usable; it just has no profile."""
    try:
        await profile_table(session, table, settings)
    except Exception:
        await session.rollback()
        logger.exception("Could not profile table %s", table.name)


async def _store_values(
    session: AsyncSession, column: SpaceColumn, values: list[str] | None
) -> None:
    """Make the column's values searchable when it is switched on and eligible, else clear them."""
    searchable = bool(column.stats and column.stats.get("searchable"))
    await session.execute(delete(ColumnValue).where(ColumnValue.column_id == column.id))
    if column.entity_matching and column.share_values and searchable and values:
        await session.execute(
            insert(ColumnValue), [{"column_id": column.id, "value": value} for value in values]
        )
        column.indexed_values = len(values)
    else:
        column.indexed_values = 0


async def _entity_columns_elsewhere(session: AsyncSession, table: SpaceTable) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(SpaceColumn)
            .join(SpaceTable, SpaceTable.id == SpaceColumn.table_id)
            .where(
                SpaceTable.space_id == table.space_id,
                SpaceTable.id != table.id,
                SpaceColumn.entity_matching.is_(True),
            )
        )
        or 0
    )


# ── Reading and editing ──────────────────────────────────────────────────────


async def get_metadata(session: AsyncSession, space_id: uuid.UUID) -> list[TableMeta]:
    return [await _table_meta(session, t) for t in await spaces.list_tables(session, space_id)]


async def _columns(session: AsyncSession, table_id: uuid.UUID) -> list[SpaceColumn]:
    return list(
        await session.scalars(
            select(SpaceColumn)
            .where(SpaceColumn.table_id == table_id)
            .order_by(SpaceColumn.position)
        )
    )


async def _table_meta(session: AsyncSession, table: SpaceTable) -> TableMeta:
    stale = False
    if table.source_type == SourceType.DELTA_PATH.value and table.profiled_at is not None:
        current = await anyio.to_thread.run_sync(spaces.delta_version, Path(table.storage_path))
        stale = current != table.delta_version
    return TableMeta(
        id=table.id,
        name=table.name,
        description=table.description,
        row_count=table.row_count,
        profiled_at=table.profiled_at,
        stale=stale,
        columns=[ColumnMeta.model_validate(c) for c in await _columns(session, table.id)],
    )


async def set_table_description(
    session: AsyncSession, access: SpaceAccess, table_id: uuid.UUID, description: str
) -> TableMeta:
    table = await spaces.get_table(session, access, table_id)
    table.description = description
    await session.commit()
    return await _table_meta(session, table)


async def update_column(
    session: AsyncSession,
    access: SpaceAccess,
    table_id: uuid.UUID,
    column_id: uuid.UUID,
    changes: ColumnMetaUpdate,
    settings: Settings,
) -> ColumnMeta:
    table = await spaces.get_table(session, access, table_id)
    column = await session.get(SpaceColumn, column_id)
    if column is None or column.table_id != table.id:
        raise NotFoundError("That column does not exist in this table.")

    if changes.description is not None:
        column.description = changes.description
    if changes.synonyms is not None:
        column.synonyms = changes.synonyms
    if changes.hidden is not None:
        column.hidden = changes.hidden
    if changes.share_values is not None:
        column.share_values = changes.share_values
    if changes.entity_matching is not None:
        column.entity_matching = changes.entity_matching
    if not column.share_values:  # without shared values there is nothing to search
        column.entity_matching = False

    if changes.entity_matching is not None or changes.share_values is not None:
        await _sync_values(session, table, column, settings)
    await session.commit()
    return ColumnMeta.model_validate(column)


async def _sync_values(
    session: AsyncSession, table: SpaceTable, column: SpaceColumn, settings: Settings
) -> None:
    values: list[str] | None = None
    if column.entity_matching:
        if not (column.stats and column.stats.get("searchable")):
            raise AppError(
                "Only text columns with at most "
                f"{profiling.VALUE_INDEX_MAX_DISTINCT:,} distinct values, each up to "
                f"{profiling.VALUE_INDEX_MAX_LENGTH} characters, can be made searchable. "
                "Profile the table first if it was just added.",
                code="not_searchable",
            )
        used = await _entity_columns_elsewhere(session, table)
        used += int(
            await session.scalar(
                select(func.count())
                .select_from(SpaceColumn)
                .where(
                    SpaceColumn.table_id == table.id,
                    SpaceColumn.entity_matching.is_(True),
                    SpaceColumn.id != column.id,
                )
            )
            or 0
        )
        if used >= profiling.VALUE_INDEX_MAX_COLUMNS:
            raise AppError(
                f"A space can have searchable values on at most "
                f"{profiling.VALUE_INDEX_MAX_COLUMNS} columns.",
                code="too_many_searchable",
            )
        values = await spaces.in_thread(
            functools.partial(
                profiling.distinct_values,
                spaces.table_source(table),
                column.name,
                timeout_seconds=settings.profile_timeout_seconds,
            )
        )
    await _store_values(session, column, values)


# ── Searching values ─────────────────────────────────────────────────────────


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_values(
    session: AsyncSession, space_id: uuid.UUID, query: str, limit: int
) -> list[ValueMatch]:
    """Values in the space that look like `query` (misspellings and partial words included)."""
    score = func.greatest(
        func.similarity(ColumnValue.value, query), func.word_similarity(query, ColumnValue.value)
    )
    rows = await session.execute(
        select(SpaceTable.name, SpaceColumn.name, ColumnValue.value, score)
        .join(SpaceColumn, SpaceColumn.id == ColumnValue.column_id)
        .join(SpaceTable, SpaceTable.id == SpaceColumn.table_id)
        .where(
            SpaceTable.space_id == space_id,
            SpaceColumn.hidden.is_(False),
            SpaceColumn.entity_matching.is_(True),
            or_(
                ColumnValue.value.op("%")(query),
                ColumnValue.value.ilike(f"%{_escape_like(query)}%", escape="\\"),
            ),
        )
        .order_by(desc(score), ColumnValue.value)
        .limit(limit)
    )
    return [ValueMatch(table=t, column=c, value=v, score=round(float(s), 3)) for t, c, v, s in rows]


# ── AI-drafted descriptions ──────────────────────────────────────────────────

DRAFT_INSTRUCTIONS = (
    "You document a table for a data assistant that writes SQL from business questions. "
    "Describe what one row is, and what each column means, using only the facts given. "
    "Do not invent units, currencies or business rules that the data does not show; if a "
    f"meaning is unclear, say so briefly. Each column description is at most "
    f"{DRAFT_DESCRIPTION_LENGTH} characters. Synonyms are other words a business user might "
    f"say for the column (at most {DRAFT_SYNONYMS}); leave them empty when none are natural. "
    "Return every column you were given, with its exact name."
)


async def draft_descriptions(
    session: AsyncSession,
    access: SpaceAccess,
    table_id: uuid.UUID,
    llm: LLMGateway,
    settings: Settings,
) -> TableDraft:
    """Ask the AI to propose descriptions and synonyms. Nothing is saved: editors review them."""
    table = await spaces.get_table(session, access, table_id)
    if table.profiled_at is None:
        await profile_table(session, table, settings)
    columns = [c for c in await _columns(session, table.id) if not c.hidden]

    facts = {
        "space": {"name": access.space.name, "description": access.space.description},
        "table": table.name,
        **({"rows": table.row_count} if table.row_count >= 0 else {}),
        "columns": [_column_facts(c) for c in columns[:DRAFT_MAX_COLUMNS]],
    }
    draft, _ = await llm.complete_json(
        [
            {"role": "system", "content": DRAFT_INSTRUCTIONS},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        TableDraft,
        purpose="describe_table",
        tier="fast",
    )
    known = {c.name for c in columns}
    cleaned: dict[str, ColumnDraft] = {}
    for item in draft.columns:
        if item.name in known and item.name not in cleaned:
            cleaned[item.name] = ColumnDraft(
                name=item.name,
                description=item.description.strip()[:DRAFT_DESCRIPTION_LENGTH],
                synonyms=[
                    s
                    for s in clean_synonyms(item.synonyms)
                    if len(s) <= 60  # same limit as editors have
                ][:DRAFT_SYNONYMS],
            )
    return TableDraft(description=draft.description.strip()[:1000], columns=list(cleaned.values()))


def _column_facts(column: SpaceColumn) -> dict:
    facts: dict = {"name": column.name, "type": column.type}
    if column.description:
        facts["current_description"] = column.description
    stats = column.stats or {}
    if stats.get("null_pct") is not None:
        facts["null_pct"] = stats["null_pct"]
    if stats.get("distinct_count") is not None:
        facts["distinct_count"] = stats["distinct_count"]
    if column.share_values:  # min, max and common values are real values from the data
        for key in ("min", "max"):
            if stats.get(key) is not None:
                facts[key] = stats[key]
        if stats.get("top_values"):
            facts["common_values"] = [v["value"] for v in stats["top_values"]]
    return facts


# ── Joins ────────────────────────────────────────────────────────────────────


async def list_joins(session: AsyncSession, space_id: uuid.UUID) -> list[JoinOut]:
    names = {t.id: t.name for t in await spaces.list_tables(session, space_id)}
    joins = await session.scalars(
        select(SpaceJoin).where(SpaceJoin.space_id == space_id).order_by(SpaceJoin.created_at)
    )
    return [_join_out(j, names) for j in joins]


def _join_out(join: SpaceJoin, names: dict[uuid.UUID, str]) -> JoinOut:
    return JoinOut(
        id=join.id,
        left_table_id=join.left_table_id,
        left_table=names[join.left_table_id],
        left_column=join.left_column,
        right_table_id=join.right_table_id,
        right_table=names[join.right_table_id],
        right_column=join.right_column,
        relationship=join.relationship,
        source=join.source,
        confirmed=join.confirmed,
    )


def _require_column(table: SpaceTable, column: str) -> None:
    if column not in {c["name"] for c in table.columns}:
        raise AppError(f"Table '{table.name}' has no column '{column}'.", code="unknown_column")


async def create_join(session: AsyncSession, access: SpaceAccess, data: JoinCreate) -> JoinOut:
    if data.left_table_id == data.right_table_id:
        raise AppError("A join needs two different tables.", code="join_same_table")
    left = await spaces.get_table(session, access, data.left_table_id)
    right = await spaces.get_table(session, access, data.right_table_id)
    _require_column(left, data.left_column)
    _require_column(right, data.right_column)
    join = SpaceJoin(
        space_id=access.space.id,
        left_table_id=left.id,
        left_column=data.left_column,
        right_table_id=right.id,
        right_column=data.right_column,
        relationship=data.relationship,
        source=JoinSource.MANUAL.value,
        confirmed=True,
    )
    session.add(join)
    await _commit_join(session)
    return _join_out(join, {left.id: left.name, right.id: right.name})


async def update_join(
    session: AsyncSession, access: SpaceAccess, join_id: uuid.UUID, changes: JoinUpdate
) -> JoinOut:
    join = await _get_join(session, access, join_id)
    left = await spaces.get_table(session, access, join.left_table_id)
    right = await spaces.get_table(session, access, join.right_table_id)
    if changes.left_column is not None:
        _require_column(left, changes.left_column)
        join.left_column = changes.left_column
    if changes.right_column is not None:
        _require_column(right, changes.right_column)
        join.right_column = changes.right_column
    if changes.relationship is not None:
        join.relationship = changes.relationship
    if changes.confirmed is not None:
        join.confirmed = changes.confirmed
    elif changes.model_fields_set:  # an editor changed it, so a person has looked at it
        join.confirmed = True
    await _commit_join(session)
    return _join_out(join, {left.id: left.name, right.id: right.name})


async def delete_join(session: AsyncSession, access: SpaceAccess, join_id: uuid.UUID) -> None:
    await session.delete(await _get_join(session, access, join_id))
    await session.commit()


async def _get_join(session: AsyncSession, access: SpaceAccess, join_id: uuid.UUID) -> SpaceJoin:
    join = await session.get(SpaceJoin, join_id)
    if join is None or join.space_id != access.space.id:
        raise NotFoundError("That join does not exist in this space.")
    return join


async def _commit_join(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("These tables are already joined on those columns.") from None


async def detect_joins(
    session: AsyncSession, access: SpaceAccess, settings: Settings
) -> list[JoinOut]:
    """Look for joins between the space's tables. New ones are saved as unconfirmed."""
    await spaces.ensure_files_only(
        session,
        access.space.id,
        "Joins in an external database come from its own foreign keys. Add any other join by hand.",
    )
    tables = await spaces.list_tables(session, access.space.id)
    by_name = {t.name: t for t in tables}
    found = await spaces.in_thread(
        functools.partial(
            profiling.detect_joins,
            [spaces.table_source(t) for t in tables],
            [JoinTable(t.name, [Column(c["name"], c["type"]) for c in t.columns]) for t in tables],
            timeout_seconds=settings.profile_timeout_seconds,
        )
    )
    known = {
        (j.left_table_id, j.left_column, j.right_table_id, j.right_column)
        for j in await session.scalars(
            select(SpaceJoin).where(SpaceJoin.space_id == access.space.id)
        )
    }
    created = []
    for item in found:
        left, right = by_name[item.left], by_name[item.right]
        forward = (left.id, item.left_column, right.id, item.right_column)
        backward = (right.id, item.right_column, left.id, item.left_column)
        if forward in known or backward in known:
            continue
        join = SpaceJoin(
            space_id=access.space.id,
            left_table_id=left.id,
            left_column=item.left_column,
            right_table_id=right.id,
            right_column=item.right_column,
            relationship=item.relationship,
            source=JoinSource.DETECTED.value,
            confirmed=False,
        )
        session.add(join)
        created.append(join)
    await session.commit()
    names = {t.id: t.name for t in tables}
    return [_join_out(j, names) for j in created]
