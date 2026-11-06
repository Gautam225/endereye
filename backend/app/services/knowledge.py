"""Instructions, glossary, example SQL and documents, and searching them.

Everything is indexed as it changes (app/services/indexing.py). Only editors see the search
stages; the AI will use the same retrieval from Step 7.
"""

import asyncio
import functools
import uuid
from pathlib import Path

import anyio
from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.db.models import Chunk, Document, DocumentStatus, KnowledgeItem, User
from app.engine.duckdb_engine import QueryFailedError
from app.rag import retrieval
from app.rag.parsing import DOCUMENT_TYPES
from app.schemas.knowledge import (
    IndexStatus,
    KnowledgeCreate,
    KnowledgeUpdate,
    PassageOut,
    RebuildOut,
    SearchHit,
    SearchOut,
)
from app.services import engines, indexing, notifications
from app.services.spaces import SpaceAccess, save_upload, space_folder

SNIPPET_CHARS = 240


# ── Instructions, glossary, example SQL ──────────────────────────────────────


async def list_items(
    session: AsyncSession, space_id: uuid.UUID, kind: str | None = None
) -> list[KnowledgeItem]:
    query = select(KnowledgeItem).where(KnowledgeItem.space_id == space_id)
    if kind:
        query = query.where(KnowledgeItem.kind == kind)
    return list(await session.scalars(query.order_by(KnowledgeItem.created_at)))


async def _get_item(
    session: AsyncSession, access: SpaceAccess, item_id: uuid.UUID
) -> KnowledgeItem:
    item = await session.get(KnowledgeItem, item_id)
    if item is None or item.space_id != access.space.id:
        raise NotFoundError("That item does not exist in this space.")
    return item


async def _check_sql(
    session: AsyncSession, space_id: uuid.UUID, sql: str, settings: Settings
) -> None:
    """An example is saved only when it passes the SQL guard and really runs on this space's data
    (a query can be well-formed and still name a column that does not exist)."""
    engine = await engines.for_space(session, space_id, settings)
    checked = engine.check(sql)
    try:
        await engine.run(
            session, checked, max_rows=1, timeout_seconds=settings.query_timeout_seconds
        )
    except QueryFailedError as exc:
        raise AppError(
            f"This SQL does not run on the space's data: {exc.message}", code="validation_error"
        ) from None


async def create_item(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: KnowledgeCreate,
    settings: Settings,
) -> KnowledgeItem:
    if data.kind == "example_sql":
        await _check_sql(session, access.space.id, data.body, settings)
    item = KnowledgeItem(
        space_id=access.space.id,
        kind=data.kind,
        title=data.title,
        body=data.body,
        trusted=data.trusted,
        note=data.note,
        created_by=user.id,
    )
    session.add(item)
    await session.commit()
    await indexing.items_changed(session, access.space.id, settings)
    return item


async def update_item(
    session: AsyncSession,
    access: SpaceAccess,
    item_id: uuid.UUID,
    data: KnowledgeUpdate,
    settings: Settings,
) -> KnowledgeItem:
    item = await _get_item(session, access, item_id)
    title = item.title if data.title is None else data.title
    body = item.body if data.body is None else data.body
    trusted = item.trusted if data.trusted is None else data.trusted
    note = item.note if data.note is None else data.note
    if not body or (item.kind in {"glossary", "example_sql", "clarification"} and not title):
        raise AppError("The text can't be empty.", code="validation_error")
    if item.kind != "example_sql" and (trusted or note):
        raise AppError("Only example SQL can be trusted or have guidance.", code="validation_error")
    if item.kind == "example_sql":
        await _check_sql(session, access.space.id, body, settings)
    item.title, item.body, item.trusted, item.note = title, body, trusted, note
    await session.commit()
    await indexing.items_changed(session, access.space.id, settings)
    return item


async def delete_item(
    session: AsyncSession, access: SpaceAccess, item_id: uuid.UUID, settings: Settings
) -> None:
    await session.delete(await _get_item(session, access, item_id))
    await session.commit()
    await indexing.items_changed(session, access.space.id, settings)


# ── Documents ────────────────────────────────────────────────────────────────


async def list_documents(
    session: AsyncSession, space_id: uuid.UUID, conversation_id: uuid.UUID | None = None
) -> list[Document]:
    """The space's documents, or (with a conversation) the ones added in that chat."""
    own = (
        Document.conversation_id.is_(None)
        if conversation_id is None
        else Document.conversation_id == conversation_id
    )
    return list(
        await session.scalars(
            select(Document).where(Document.space_id == space_id, own).order_by(Document.created_at)
        )
    )


async def uploader_names(
    session: AsyncSession, documents: list[Document]
) -> dict[uuid.UUID | None, str]:
    ids = {d.created_by for d in documents if d.created_by}
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return {user_id: name for user_id, name in rows.all()}


async def _space_document(
    session: AsyncSession, access: SpaceAccess, document_id: uuid.UUID
) -> Document:
    document = await session.get(Document, document_id)
    if (
        document is None
        or document.space_id != access.space.id
        or document.conversation_id is not None
    ):
        raise NotFoundError("That document does not exist in this space.")
    return document


async def rename_document(
    session: AsyncSession, access: SpaceAccess, document_id: uuid.UUID, title: str
) -> Document:
    document = await _space_document(session, access, document_id)
    document.title = title
    if document.status == DocumentStatus.READY.value:
        document.status = DocumentStatus.PROCESSING.value
    await session.commit()
    return document


async def prepare_reread(
    session: AsyncSession, access: SpaceAccess, document_id: uuid.UUID
) -> Document:
    document = await _space_document(session, access, document_id)
    document.status = DocumentStatus.PROCESSING.value
    document.error = None
    await session.commit()
    return document


def _title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip() or filename


async def add_document(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    upload: UploadFile,
    settings: Settings,
    conversation_id: uuid.UUID | None = None,
) -> Document:
    filename = Path(upload.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in DOCUMENT_TYPES:
        kinds = ", ".join(sorted(DOCUMENT_TYPES))
        raise AppError(f"This file type can't be used. Upload one of: {kinds}.", code="file_type")
    folder = space_folder(settings, access.space.id) / "documents"
    path = await save_upload(upload, folder, extension, settings.max_upload_mb)
    document = Document(
        space_id=access.space.id,
        filename=filename,
        title=_title(filename),
        storage_path=str(path),
        size_bytes=(await anyio.Path(path).stat()).st_size,
        status=DocumentStatus.PROCESSING.value,
        parser=settings.document_parser,
        created_by=user.id,
        conversation_id=conversation_id,
    )
    session.add(document)
    await session.commit()
    return document


async def _tell_document(session: AsyncSession, document: Document) -> None:
    """The person who uploaded it hears that it is ready to use, or why it was not."""
    ready = document.status == DocumentStatus.READY.value
    place = (
        f"/spaces/{document.space_id}/chat/{document.conversation_id}"
        if document.conversation_id
        else f"/spaces/{document.space_id}?tab=library"
    )
    await notifications.notify(
        session,
        [document.created_by],
        kind="document_ready" if ready else "document_failed",
        level="success" if ready else "error",
        title=f"{document.filename} is ready"
        if ready
        else f"{document.filename} could not be read",
        body=(
            f"{document.chunk_count} sections are searchable now."
            if ready
            else (document.error or "The file could not be read.")[:300]
        ),
        link=place,
    )


def schedule_indexing(
    sessionmaker: async_sessionmaker[AsyncSession],
    tasks: set[asyncio.Task],
    document_id: uuid.UUID,
    settings: Settings,
) -> None:
    """Read and index a saved document in the background, so the upload request can end (and the
    page can be refreshed) without losing the work. The document is `processing` until then."""

    async def work() -> None:
        async with sessionmaker() as session:
            document = await session.get(Document, document_id)
            if document is not None and document.status == DocumentStatus.PROCESSING.value:
                await indexing.index_document(session, document, settings)
                await _tell_document(session, document)

    task = asyncio.create_task(work())
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def fail_interrupted_documents(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """Documents left 'processing' by a restart will never finish: say so, so they can be
    deleted and uploaded again."""
    async with sessionmaker() as session:
        result = await session.execute(
            update(Document)
            .where(Document.status == DocumentStatus.PROCESSING.value)
            .values(
                status=DocumentStatus.FAILED.value,
                error="The app restarted while this document was being read. Upload it again.",
            )
        )
        await session.commit()
        return result.rowcount or 0


async def delete_document(
    session: AsyncSession,
    access: SpaceAccess,
    document_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> None:
    document = await session.get(Document, document_id)
    if (
        document is None
        or document.space_id != access.space.id
        or document.conversation_id != conversation_id
    ):
        raise NotFoundError("That document does not exist in this space.")
    path = Path(document.storage_path)
    await indexing.remove_document(session, document)
    await session.delete(document)
    await session.commit()
    await anyio.Path(path).unlink(missing_ok=True)


# ── Index and search ─────────────────────────────────────────────────────────


async def status(session: AsyncSession, space_id: uuid.UUID, settings: Settings) -> IndexStatus:
    counts = dict(
        (
            await session.execute(
                select(Chunk.source_type, func.count())
                .where(Chunk.space_id == space_id, Chunk.conversation_id.is_(None))
                .group_by(Chunk.source_type)
            )
        ).all()
    )
    documents = await list_documents(session, space_id)
    return IndexStatus(
        chunks=counts,
        documents=len(documents),
        failed_documents=sum(d.status == DocumentStatus.FAILED.value for d in documents),
        embedding_model=settings.embedding_model,
        rerank_model=settings.rerank_model,
        chunk_tokens=settings.chunk_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        document_parser=settings.document_parser,
    )


async def rebuild(session: AsyncSession, space_id: uuid.UUID, settings: Settings) -> RebuildOut:
    counts = await indexing.rebuild(session, space_id, settings)
    return RebuildOut(added=counts.added, updated=counts.updated, removed=counts.removed)


async def search(
    session: AsyncSession, access: SpaceAccess, query: str, settings: Settings
) -> SearchOut:
    embedder = await indexing.load_embedder(settings)
    reranker = await indexing.load_reranker(settings)
    result = await retrieval.search(
        session,
        access.space.id,
        query,
        embed_query=embedder.embed_query,
        rerank=functools.partial(_rerank, reranker),
        threshold=settings.rerank_threshold,
    )
    return SearchOut(
        query=result.query,
        hits=[
            SearchHit(
                id=c.id,
                source_type=c.source_type,
                header=c.header,
                snippet=_snippet(c.text),
                vector_rank=c.vector_rank,
                vector_distance=None if c.vector_distance is None else round(c.vector_distance, 4),
                bm25_rank=c.bm25_rank,
                bm25_score=None if c.bm25_score is None else round(c.bm25_score, 3),
                fused_rank=c.fused_rank,
                rerank_score=None if c.rerank_score is None else round(c.rerank_score, 3),
                final_rank=c.final_rank,
            )
            for c in result.candidates
        ],
        passages=[
            PassageOut(
                header=p.header,
                text=p.text,
                source_type=p.source_type,
                score=round(p.score, 3),
                chunk_ids=list(p.chunk_ids),
                meta=p.meta,
            )
            for p in result.passages
        ],
        timings_ms=result.timings_ms,
    )


def _rerank(reranker, query: str, passages: list[str]) -> list[float]:
    return reranker.score(query, passages)


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_CHARS else flat[: SNIPPET_CHARS - 1] + "…"
