"""Gathers what the AI needs for one question: the right tables, rules, examples and values.

Retrieval (app/rag/retrieval.py) picks the relevant pieces; this module turns them into the
context for the prompt. Instructions are always included, because they are global rules.
"""

import re
import uuid
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.charts import is_temporal
from app.chat.prompts import (
    ColumnContext,
    Context,
    DefinitionContext,
    ExampleContext,
    TableContext,
)
from app.core.config import Settings
from app.db.models import Document, KnowledgeItem, SqlExpression
from app.rag import cards, retrieval
from app.rag.models import Embedder, Reranker
from app.services import indexing
from app.services import metadata as metadata_service
from app.services.access_rules import Restrictions

MAX_TABLES = 6
MAX_EXAMPLES = 3
MAX_DOC_PASSAGES = 6  # passages from documents in one prompt, never whole documents
DOC_BUDGET_CHARS = 6000  # about 1,500 tokens of document text
MAX_COVERED_DOCS = 5
MAX_INSTRUCTIONS = 30
MAX_CLARIFICATIONS = 10
MAX_DEFINITIONS = 8
MAX_VALUES = 8
MAX_VALUE_QUERIES = 12
DOCUMENT_CHARS = 1500
INSTRUCTION_CHARS = 600
COMMON_VALUES_SHOWN = 5
LOW_CARDINALITY = 25
VALUE_MATCH_SCORE = 0.55

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9&'.-]*")
_FILLER = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "what",
        "which",
        "who",
        "how",
        "many",
        "much",
        "show",
        "list",
        "give",
        "tell",
        "me",
        "by",
        "per",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "top",
        "all",
        "any",
        "each",
        "last",
        "first",
        "month",
        "year",
        "week",
        "day",
        "total",
        "average",
        "count",
        "number",
    ]
)


@dataclass(slots=True)
class BuiltContext:
    context: Context
    table_names: list[str]  # every table in the space (what the SQL guard allows)
    sources: list[dict[str, Any]] = field(default_factory=list)  # what retrieval found
    trusted_sql: dict[str, str] = field(default_factory=dict)  # normalised SQL -> question
    # The document passages shown to the AI, each under a tag it cites as [S1]:
    # [{"tag", "document_id", "title", "page", "text"}]
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieval_ms: int = 0


def normalise_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").lower().split())


def value_candidates(question: str) -> list[str]:
    """Words and word pairs from the question that might be a value in the data."""
    words = [w.strip(".'-&") for w in _WORD.findall(question)]
    words = [w for w in words if len(w) >= 3 and w.lower() not in _FILLER]
    pairs = [f"{a} {b}" for a, b in pairwise(words)]
    seen: dict[str, None] = {}
    for candidate in [*pairs, *words]:
        seen.setdefault(candidate, None)
    return list(seen)[:MAX_VALUE_QUERIES]


def select_tables(
    passages: list[retrieval.Passage],
    tables: list[cards.TableInfo],
    joins: list[cards.JoinInfo],
    limit: int = MAX_TABLES,
) -> list[cards.TableInfo]:
    """The tables the retrieved pieces point at, then the tables joined to them."""
    by_name = {t.name: t for t in tables}
    chosen: list[str] = []
    for passage in passages:
        name = passage.meta.get("table")
        if passage.source_type in {"table", "column"} and name in by_name and name not in chosen:
            chosen.append(name)
    for join in joins:
        for here, there in (
            (join.left_table, join.right_table),
            (join.right_table, join.left_table),
        ):
            if here in chosen and there not in chosen and there in by_name:
                chosen.append(there)
    if not chosen:  # nothing matched: show whatever fits
        chosen = [t.name for t in tables]
    return [by_name[name] for name in chosen[:limit]]


def table_context(table: cards.TableInfo, unseen: frozenset[str] = frozenset()) -> TableContext:
    """What the AI is told about a table. `unseen` are the columns this person may not read: they
    are left out, with their example values, as if the column did not exist."""
    columns = []
    for column in table.columns:
        if column.hidden or column.name in unseen:
            continue
        stats = column.stats or {}
        distinct = stats.get("distinct_count")
        common: tuple[str, ...] = ()
        if column.share_values and distinct is not None and distinct <= LOW_CARDINALITY:
            common = tuple(v["value"] for v in stats.get("top_values", [])[:COMMON_VALUES_SHOWN])
        low, high = stats.get("min"), stats.get("max")
        span = (
            (str(low)[:10], str(high)[:10])
            if column.share_values and is_temporal(column.type) and low and high
            else None
        )
        columns.append(
            ColumnContext(
                column.name,
                column.type,
                column.description,
                tuple(column.synonyms),
                common,
                span,
            )
        )
    return TableContext(
        table.name,
        table.description,
        table.row_count,
        tuple(columns),
        approximate=table.approximate,
    )


async def build_context(
    session: AsyncSession,
    space_id: uuid.UUID,
    question: str,
    *,
    embedder: Embedder,
    reranker: Reranker,
    settings: Settings,
    conversation_id: uuid.UUID | None = None,
    mentions: list[dict[str, str]] | None = None,
    restrictions: Restrictions | None = None,
) -> BuiltContext:
    restrictions = restrictions or {}
    unseen = {name: r.unseen for name, r in restrictions.items()}
    mentions = mentions or []
    pointed_docs = [m for m in mentions if m.get("kind", "document") == "document"]
    pointed_tables = [m for m in mentions if m.get("kind") == "table"]
    keys = frozenset(f"doc:{m['id']}" for m in pointed_docs)
    scope = retrieval.Scope(conversation_id, keys or None)
    result = await retrieval.search(
        session,
        space_id,
        question,
        embed_query=embedder.embed_query,
        rerank=reranker.score,
        threshold=settings.rerank_threshold,
        scope=scope,
    )
    tables, joins = await indexing.load_schema(session, space_id)
    chosen = select_tables(result.passages, tables, joins)
    if pointed_tables:  # the person named the tables to use: those and no others
        wanted = {m["id"] for m in pointed_tables}
        chosen = [t for t in tables if t.id in wanted] or chosen
    chosen_names = {t.name for t in chosen}

    context = Context(tables=[table_context(t, unseen.get(t.name, frozenset())) for t in chosen])
    context.mentioned = [f"@{m['name']}" for m in pointed_docs]
    context.mentioned_tables = [
        f"@{m['name']}" for m in pointed_tables if m["id"] in {t.id for t in chosen}
    ]
    context.joins = [
        f"{j.left_table}.{j.left_column} = {j.right_table}.{j.right_column} "
        f"({j.relationship.replace('_', ' ')})"
        for j in joins
        if j.left_table in chosen_names and j.right_table in chosen_names
    ]
    items = await session.scalars(
        select(KnowledgeItem)
        .where(KnowledgeItem.space_id == space_id, KnowledgeItem.kind == "instruction")
        .order_by(KnowledgeItem.created_at)
        .limit(MAX_INSTRUCTIONS)
    )
    context.instructions = [i.body[:INSTRUCTION_CHARS] for i in items]
    rules = await session.scalars(
        select(KnowledgeItem)
        .where(KnowledgeItem.space_id == space_id, KnowledgeItem.kind == "clarification")
        .order_by(KnowledgeItem.created_at)
        .limit(MAX_CLARIFICATIONS)
    )
    context.clarifications = [(r.title, r.body[:INSTRUCTION_CHARS]) for r in rules]
    defaults = await session.scalars(
        select(SqlExpression)
        .where(SqlExpression.space_id == space_id, SqlExpression.is_default.is_(True))
        .order_by(SqlExpression.created_at)
    )
    context.default_filters = [
        DefinitionContext(d.name, d.type, d.expression, d.table_name, d.description)
        for d in defaults
    ]
    default_names = {d.name for d in context.default_filters}

    built = BuiltContext(
        context, [t.name for t in tables], retrieval_ms=sum(result.timings_ms.values())
    )
    doc_passages: list[retrieval.Passage] = []
    for passage in result.passages:
        _add_source(
            built.sources,
            passage.source_type,
            str(passage.meta.get("document", passage.header))
            if passage.source_type == "document"
            else passage.header,
        )
        if passage.source_type == "glossary" and len(context.glossary) < MAX_INSTRUCTIONS:
            term = str(passage.meta.get("term", passage.header))
            context.glossary.append((term, passage.text.removeprefix(f"{term}:").strip()))
        elif passage.source_type == "example_sql" and len(context.examples) < MAX_EXAMPLES:
            sql = str(passage.meta.get("sql", ""))
            question_text = str(passage.meta.get("question", passage.text))
            note = passage.text.removeprefix(question_text).strip()
            context.examples.append(
                ExampleContext(question_text, sql, bool(passage.meta.get("trusted")), note)
            )
            if passage.meta.get("trusted"):
                built.trusted_sql[normalise_sql(sql)] = question_text
        elif passage.source_type == "expression" and len(context.definitions) < MAX_DEFINITIONS:
            name = str(passage.meta.get("name", passage.header))
            if name not in default_names:  # default filters are shown in their own section
                context.definitions.append(
                    DefinitionContext(
                        name,
                        str(passage.meta.get("kind", "measure")),
                        str(passage.meta.get("sql", "")),
                        passage.meta.get("table"),
                        str(passage.meta.get("description", "")),
                    )
                )
        elif passage.source_type == "document":
            doc_passages.append(passage)

    # A question about "both documents" must see each of them, not only the one that matches best.
    doc_passages += await _cover_missing_documents(
        session,
        space_id,
        question,
        conversation_id=conversation_id,
        document_keys=keys,
        present={str(p.meta.get("document")) for p in doc_passages},
        embedder=embedder,
        reranker=reranker,
        settings=settings,
    )
    for passage in doc_passages:
        title = str(passage.meta.get("document", "document"))
        if not any(s["type"] == "document" and s["header"] == title for s in built.sources):
            _add_source(built.sources, "document", title)
    context.documents, built.citations = _balanced_documents(doc_passages)

    context.values = await _matching_values(session, space_id, question, chosen_names, unseen)
    return built


def _add_source(sources: list[dict[str, Any]], kind: str, header: str) -> None:
    """One entry per thing used (a document once, however many of its passages were found)."""
    for source in sources:
        if source["type"] == kind and source["header"] == header:
            source["passages"] += 1
            return
    sources.append({"type": kind, "header": header, "passages": 1})


def _balanced_documents(
    passages: list[retrieval.Passage],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Passages taken in turn from each document, best first, within a fixed size budget.
    Each gets a tag ([S1], [S2]...) the AI cites, and a record of where it came from."""
    groups: dict[str, list[retrieval.Passage]] = {}
    for passage in passages:
        groups.setdefault(str(passage.meta.get("document", "document")), []).append(passage)
    chosen: list[tuple[str, str]] = []
    cites: list[dict[str, Any]] = []
    used = 0
    while any(groups.values()) and len(chosen) < MAX_DOC_PASSAGES:
        for title, queue in groups.items():
            if not queue or len(chosen) >= MAX_DOC_PASSAGES:
                continue
            passage = queue.pop(0)
            text = passage.text[:DOCUMENT_CHARS]
            if used + len(text) > DOC_BUDGET_CHARS and chosen:
                return chosen, cites
            tag = f"S{len(chosen) + 1}"
            page = passage.meta.get("page")
            path = " > ".join(passage.meta.get("section_path") or [])
            where = f"{title}, page {page}" if page else (f"{title} > {path}" if path else title)
            chosen.append((f"{tag}: {where}", text))
            cites.append(
                {
                    "tag": tag,
                    "document_id": passage.meta.get("document_id"),
                    "title": title,
                    "page": page,
                    "ocr": bool(passage.meta.get("ocr")),
                    "section": path or None,
                    "text": text,
                }
            )
            used += len(text)
    return chosen, cites


async def _cover_missing_documents(
    session: AsyncSession,
    space_id: uuid.UUID,
    question: str,
    *,
    conversation_id: uuid.UUID | None,
    document_keys: frozenset[str],
    present: set[str],
    embedder: Embedder,
    reranker: Reranker,
    settings: Settings,
) -> list[retrieval.Passage]:
    """For each document of this chat (or each one mentioned) that the search did not surface,
    its own best passages. Only passages are ever added, never a whole document."""
    if conversation_id is None and not document_keys:
        return []
    if document_keys:
        ids = [uuid.UUID(key.removeprefix("doc:")) for key in document_keys]
        where = Document.id.in_(ids)
    else:
        where = Document.conversation_id == conversation_id
    documents = list(
        await session.execute(
            select(Document.title, Document.id)
            .where(Document.space_id == space_id, Document.status == "ready", where)
            .order_by(Document.created_at)
        )
    )
    if len(documents) < 2:
        return []
    extra: list[retrieval.Passage] = []
    for title, doc_id in documents[:MAX_COVERED_DOCS]:
        if title in present:
            continue
        found = await retrieval.search(
            session,
            space_id,
            question,
            embed_query=embedder.embed_query,
            rerank=reranker.score,
            threshold=settings.rerank_threshold,
            types={"document"},
            scope=retrieval.Scope(conversation_id, frozenset({f"doc:{doc_id}"})),
        )
        extra += [p for p in found.passages if p.source_type == "document"][:2]
    return extra


async def _matching_values(
    session: AsyncSession,
    space_id: uuid.UUID,
    question: str,
    tables: set[str],
    unseen: dict[str, frozenset[str]],
) -> list[str]:
    found: dict[str, None] = {}
    for candidate in value_candidates(question):
        for match in await metadata_service.search_values(session, space_id, candidate, 3):
            exact = match.value.lower() == candidate.lower()
            if match.column in unseen.get(match.table, frozenset()):
                continue  # a value of a column this person may not read
            if match.table in tables and (exact or match.score >= VALUE_MATCH_SCORE):
                found.setdefault(
                    f"{match.table}.{match.column} contains the value '{match.value}'", None
                )
        if len(found) >= MAX_VALUES:
            break
    return list(found)[:MAX_VALUES]
