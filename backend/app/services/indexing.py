"""Keeps a space's searchable chunks in step with its tables, metadata, and knowledge.

Schema cards, instructions, glossary terms and example SQL are cheap to rebuild: chunks whose
content did not change keep their vectors, and only new or changed ones are embedded. A
document is parsed and chunked once, when it is added (or when the index is rebuilt).
"""

import functools
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    Chunk,
    ChunkType,
    Document,
    DocumentStatus,
    KnowledgeItem,
    Space,
    SpaceColumn,
    SpaceJoin,
    SpaceTable,
    SqlExpression,
)
from app.rag import cards
from app.rag.cards import ChunkSpec
from app.rag.chunking import Splitter
from app.rag.models import Embedder, ModelConfig, Reranker, get_embedder, get_reranker
from app.rag.ocr import OcrOptions
from app.rag.parsing import read_document
from app.services.spaces import in_thread

logger = logging.getLogger(__name__)

SCHEMA_TYPES = {ChunkType.TABLE.value, ChunkType.COLUMN.value}
ITEM_TYPES = {
    ChunkType.INSTRUCTION.value,
    ChunkType.GLOSSARY.value,
    ChunkType.EXAMPLE_SQL.value,
    ChunkType.CLARIFICATION.value,
    ChunkType.EXPRESSION.value,
}
DOCUMENT_TYPES = {ChunkType.DOCUMENT.value}


@dataclass(frozen=True, slots=True)
class SyncCounts:
    added: int = 0
    updated: int = 0
    removed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


# ── Models ───────────────────────────────────────────────────────────────────


def model_config(settings: Settings) -> ModelConfig:
    models_dir = settings.models_dir
    if not models_dir.is_absolute():
        from app.core.config import PROJECT_ROOT

        models_dir = PROJECT_ROOT / models_dir
    return ModelConfig(settings.embedding_model, settings.rerank_model, models_dir)


async def load_embedder(settings: Settings) -> Embedder:
    return await in_thread(get_embedder, model_config(settings))


async def load_reranker(settings: Settings) -> Reranker:
    return await in_thread(get_reranker, model_config(settings))


def make_splitter(embedder: Embedder, settings: Settings) -> Splitter:
    return Splitter(
        embedder.count,
        embedder.tail,
        text_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )


# ── Storing chunks ───────────────────────────────────────────────────────────


async def sync_chunks(
    session: AsyncSession,
    space_id: uuid.UUID,
    specs: list[ChunkSpec],
    *,
    types: set[str],
    embedder: Embedder,
    source_key: str | None = None,
    conversation_id: uuid.UUID | None = None,
) -> SyncCounts:
    """Make the stored chunks of these types (optionally of one source) equal `specs`."""
    query = select(Chunk.id, Chunk.source_key, Chunk.position, Chunk.content_hash).where(
        Chunk.space_id == space_id, Chunk.source_type.in_(types)
    )
    if source_key is not None:
        query = query.where(Chunk.source_key == source_key)
    existing = {(row[1], row[2]): (row[0], row[3]) for row in await session.execute(query)}
    wanted = {(spec.source_key, spec.position): spec for spec in specs}

    removed = [chunk_id for key, (chunk_id, _) in existing.items() if key not in wanted]
    changed = [
        spec
        for key, spec in wanted.items()
        if key not in existing or existing[key][1] != spec.content_hash
    ]
    if not removed and not changed:
        return SyncCounts()

    vectors = (
        await in_thread(embedder.embed, [spec.embed_text for spec in changed]) if changed else []
    )
    if removed:
        await session.execute(delete(Chunk).where(Chunk.id.in_(removed)))
    added = updated = 0
    new_rows = []
    for spec, vector in zip(changed, vectors, strict=True):
        values = {
            "source_type": spec.source_type,
            "header": spec.header,
            "text": spec.text,
            "meta": spec.meta,
            "content_hash": spec.content_hash,
            "embedding": vector,
            "conversation_id": conversation_id,
        }
        found = existing.get((spec.source_key, spec.position))
        if found is None:
            new_rows.append(
                {
                    "space_id": space_id,
                    "source_key": spec.source_key,
                    "position": spec.position,
                    **values,
                }
            )
            added += 1
        else:
            await session.execute(update(Chunk).where(Chunk.id == found[0]).values(**values))
            updated += 1
    if new_rows:
        await session.execute(insert(Chunk), new_rows)
    await session.execute(
        update(Space).where(Space.id == space_id).values(index_version=Space.index_version + 1)
    )
    await session.commit()
    return SyncCounts(added, updated, len(removed))


# ── Schema, items, documents ─────────────────────────────────────────────────


async def load_schema(
    session: AsyncSession, space_id: uuid.UUID
) -> tuple[list[cards.TableInfo], list[cards.JoinInfo]]:
    tables = list(
        await session.scalars(
            select(SpaceTable).where(SpaceTable.space_id == space_id).order_by(SpaceTable.name)
        )
    )
    columns = list(
        await session.scalars(
            select(SpaceColumn)
            .where(SpaceColumn.table_id.in_([t.id for t in tables]))
            .order_by(SpaceColumn.table_id, SpaceColumn.position)
        )
    )
    names = {t.id: t.name for t in tables}
    infos = [
        cards.TableInfo(
            str(t.id),
            t.name,
            t.description,
            t.row_count,
            tuple(
                cards.ColumnInfo(
                    str(c.id),
                    c.name,
                    c.type,
                    c.description,
                    tuple(c.synonyms),
                    c.hidden,
                    c.share_values,
                    c.stats,
                )
                for c in columns
                if c.table_id == t.id
            ),
            approximate=t.source_type == "external",
        )
        for t in tables
    ]
    joins = [
        cards.JoinInfo(
            names[j.left_table_id],
            j.left_column,
            names[j.right_table_id],
            j.right_column,
            j.relationship,
        )
        # A join found by looking at names and values is only a guess until an editor confirms it.
        for j in await session.scalars(
            select(SpaceJoin).where(SpaceJoin.space_id == space_id, SpaceJoin.confirmed.is_(True))
        )
    ]
    return infos, joins


async def reindex_schema(
    session: AsyncSession, space_id: uuid.UUID, settings: Settings
) -> SyncCounts:
    embedder = await load_embedder(settings)
    tables, joins = await load_schema(session, space_id)
    specs = cards.schema_chunks(tables, joins, make_splitter(embedder, settings))
    return await sync_chunks(session, space_id, specs, types=SCHEMA_TYPES, embedder=embedder)


async def reindex_items(
    session: AsyncSession, space_id: uuid.UUID, settings: Settings
) -> SyncCounts:
    embedder = await load_embedder(settings)
    items = await session.scalars(
        select(KnowledgeItem)
        .where(KnowledgeItem.space_id == space_id)
        .order_by(KnowledgeItem.created_at)
    )
    infos = [cards.ItemInfo(str(i.id), i.kind, i.title, i.body, i.trusted, i.note) for i in items]
    splitter = make_splitter(embedder, settings)
    expressions = await session.scalars(
        select(SqlExpression)
        .where(SqlExpression.space_id == space_id)
        .order_by(SqlExpression.created_at)
    )
    definitions = [
        cards.ExpressionInfo(
            str(e.id),
            e.name,
            e.type,
            e.expression,
            e.table_name,
            e.description,
            tuple(e.synonyms),
            e.is_default,
        )
        for e in expressions
    ]
    specs = cards.item_chunks(infos, splitter) + cards.expression_chunks(definitions, splitter)
    return await sync_chunks(session, space_id, specs, types=ITEM_TYPES, embedder=embedder)


async def index_document(
    session: AsyncSession, document: Document, settings: Settings
) -> SyncCounts:
    """Parse a stored document into Markdown, chunk it, and index it. Marks failure on it."""
    embedder = await load_embedder(settings)
    try:
        reading = await in_thread(
            read_document,
            Path(document.storage_path),
            document.parser,
            document.filename,
            OcrOptions(settings.document_ocr, settings.document_ocr_max_pages),
        )
        pages = reading.pages
        specs = cards.document_chunks(
            str(document.id),
            document.title,
            document.filename,
            pages,
            make_splitter(embedder, settings),
        )
        counts = await sync_chunks(
            session,
            document.space_id,
            specs,
            types=DOCUMENT_TYPES,
            embedder=embedder,
            source_key=f"doc:{document.id}",
            conversation_id=document.conversation_id,
        )
    except Exception as exc:
        await session.rollback()
        document.status = DocumentStatus.FAILED.value
        document.error = str(exc)[:1000] or type(exc).__name__
        document.chunk_count = 0
        await session.commit()
        logger.warning("Could not index document %s: %s", document.filename, exc)
        return SyncCounts()
    document.status = DocumentStatus.READY.value
    document.error = None
    document.chunk_count = len(specs)
    numbers = [p.number for p in pages if p.number is not None]
    document.page_count = max(numbers) if numbers else None
    document.ocr_pages = [p.number for p in pages if p.ocr and p.number is not None]
    document.unread_pages = reading.unread
    await session.commit()
    return counts


async def remove_document(session: AsyncSession, document: Document) -> None:
    await session.execute(
        delete(Chunk).where(
            Chunk.space_id == document.space_id, Chunk.source_key == f"doc:{document.id}"
        )
    )
    await session.execute(
        update(Space)
        .where(Space.id == document.space_id)
        .values(index_version=Space.index_version + 1)
    )


async def rebuild(session: AsyncSession, space_id: uuid.UUID, settings: Settings) -> SyncCounts:
    """Rebuild everything for a space: schema, items, and every stored document."""
    total = [
        await reindex_schema(session, space_id, settings),
        await reindex_items(session, space_id, settings),
    ]
    documents = await session.scalars(select(Document).where(Document.space_id == space_id))
    for document in documents:
        total.append(await index_document(session, document, settings))
    return SyncCounts(
        sum(c.added for c in total), sum(c.updated for c in total), sum(c.removed for c in total)
    )


# ── Safe wrappers: saving metadata must not fail because indexing did ───────


async def schema_changed(session: AsyncSession, space_id: uuid.UUID, settings: Settings) -> None:
    await _quietly(
        functools.partial(reindex_schema, session, space_id, settings), "schema", session
    )


async def items_changed(session: AsyncSession, space_id: uuid.UUID, settings: Settings) -> None:
    await _quietly(functools.partial(reindex_items, session, space_id, settings), "items", session)


async def _quietly(action, what: str, session: AsyncSession) -> None:
    try:
        await action()
    except Exception:
        await session.rollback()
        logger.exception("Could not update the search index (%s)", what)
