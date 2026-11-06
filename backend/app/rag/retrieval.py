"""Hybrid retrieval over a space's chunks, with every stage recorded.

    question ─┬─▶ vector search (pgvector, top 40) ─┐
              └─▶ BM25 search   (bm25s,   top 40) ─┴─▶ Reciprocal Rank Fusion
                  ─▶ rerank the best 30 (local cross-encoder) ─▶ keep 5-10 ─▶ the AI

Only the space's own chunks are searched (the space filter applies before ranking).
"""

import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anyio
import bm25s
from bm25s.stopwords import STOPWORDS_EN
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Space

VECTOR_K = 40
BM25_K = 40
RERANK_CANDIDATES = 30
RRF_K = 60  # the usual constant; it damps the influence of any one list's top ranks
MIN_FINAL = 5
MAX_FINAL = 10
HNSW_EF_SEARCH = 100
SNIPPET_CHARS = 280

# Question words and polite filler carry no meaning for keyword matching.
_STOP = frozenset(STOPWORDS_EN) | {
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "how",
    "many",
    "much",
    "show",
    "list",
    "give",
    "tell",
    "me",
    "please",
    "can",
    "could",
    "would",
    "should",
    "does",
    "did",
    "has",
    "have",
    "had",
    "get",
    "find",
    "us",
    "our",
    "we",
    "you",
    "your",
}
_WORD = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class Scope:
    """Which chunks a search may use. Documents added in a chat belong to that conversation
    only; when documents are mentioned, only those documents are searched (other kinds of
    knowledge still are)."""

    conversation_id: uuid.UUID | None = None
    document_keys: frozenset[str] | None = None


def _conditions(types: set[str] | None, scope: Scope) -> list[Any]:
    own = Chunk.conversation_id.is_(None)
    if scope.conversation_id is not None:
        own = or_(own, Chunk.conversation_id == scope.conversation_id)
    conditions: list[Any] = [own]
    if types:
        conditions.append(Chunk.source_type.in_(types))
    if scope.document_keys:
        conditions.append(
            or_(Chunk.source_type != "document", Chunk.source_key.in_(scope.document_keys))
        )
    return conditions


@dataclass(slots=True)
class Candidate:
    id: int
    source_type: str
    source_key: str
    position: int
    header: str
    text: str
    meta: dict[str, Any]
    vector_rank: int | None = None
    vector_distance: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    fused_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None
    final_rank: int | None = None  # set when it was kept


@dataclass(frozen=True, slots=True)
class Passage:
    """What the AI is shown: one chunk, or neighbouring pieces of a section joined back."""

    header: str
    text: str
    source_type: str
    score: float
    chunk_ids: tuple[int, ...]
    meta: dict[str, Any]


@dataclass(slots=True)
class SearchResult:
    query: str
    candidates: list[Candidate]
    passages: list[Passage]
    timings_ms: dict[str, int] = field(default_factory=dict)


def tokens(value: str) -> list[str]:
    """Words for BM25: lower case, no stop words, plurals trimmed, `customer_id` also gives
    `customer` and `id` (so a question about customers finds a customer_id column)."""
    out: list[str] = []
    for word in _WORD.findall(value.lower()):
        parts = [word, *[p for p in word.split("_") if p]] if "_" in word else [word]
        for part in dict.fromkeys(parts):
            if part in _STOP or (len(part) < 2 and not part.isdigit()):
                continue
            out.append(
                part[:-1]
                if len(part) > 3 and part.endswith("s") and not part.endswith("ss")
                else part
            )
    return out


@dataclass(slots=True)
class _Bm25Index:
    version: int
    retriever: bm25s.BM25 | None
    ids: list[int]


class _Bm25Cache:
    """One keyword index per space, rebuilt when the space's `index_version` moves on."""

    def __init__(self, size: int = 32) -> None:
        self._entries: OrderedDict[uuid.UUID, _Bm25Index] = OrderedDict()
        self._size = size

    def get(self, space_id: uuid.UUID, version: int) -> _Bm25Index | None:
        entry = self._entries.get(space_id)
        if entry is not None and entry.version == version:
            self._entries.move_to_end(space_id)
            return entry
        return None

    def put(self, space_id: uuid.UUID, entry: _Bm25Index) -> None:
        self._entries[space_id] = entry
        self._entries.move_to_end(space_id)
        while len(self._entries) > self._size:
            self._entries.popitem(last=False)


_cache = _Bm25Cache()


def _build_bm25(rows: list[tuple[int, str, str]], version: int) -> _Bm25Index:
    ids = [row[0] for row in rows]
    corpus = [tokens(f"{header}\n{body}") for _, header, body in rows]
    corpus = [doc or ["_empty_"] for doc in corpus]
    if not corpus:
        return _Bm25Index(version, None, [])
    retriever = bm25s.BM25()
    retriever.index(corpus, show_progress=False)
    return _Bm25Index(version, retriever, ids)


async def _bm25_search(
    session: AsyncSession,
    space_id: uuid.UUID,
    version: int,
    query: str,
    allowed: set[int] | None,
) -> list[tuple[int, float]]:
    index = _cache.get(space_id, version)
    if index is None:
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.header, Chunk.text)
                .where(Chunk.space_id == space_id)
                .order_by(Chunk.id)
            )
        ).all()
        index = await anyio.to_thread.run_sync(
            _build_bm25, [(r[0], r[1], r[2]) for r in rows], version
        )
        _cache.put(space_id, index)
    if index.retriever is None:
        return []
    known = index.retriever.vocab_dict
    words = [w for w in tokens(query) if w in known]
    if not words:
        return []
    k = min(BM25_K if allowed is None else len(index.ids), len(index.ids))
    positions, scores = index.retriever.retrieve([words], k=k, show_progress=False)
    found = [
        (index.ids[int(p)], float(s))
        for p, s in zip(positions[0], scores[0], strict=True)
        if s > 0 and (allowed is None or index.ids[int(p)] in allowed)
    ]
    return found[:BM25_K]


async def _vector_search(
    session: AsyncSession,
    space_id: uuid.UUID,
    vector: list[float],
    types: set[str] | None,
    scope: Scope,
) -> list[tuple[int, float]]:
    try:
        async with session.begin_nested():  # older pgvector has no iterative scan
            await session.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
    except Exception:
        pass
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}"))
    distance = Chunk.embedding.cosine_distance(vector)
    statement = select(Chunk.id, distance).where(
        Chunk.space_id == space_id, *_conditions(types, scope)
    )
    rows = await session.execute(statement.order_by(distance).limit(VECTOR_K))
    return [(row[0], float(row[1])) for row in rows]


def reciprocal_rank_fusion(*rankings: list[int]) -> dict[int, float]:
    """Score each id by the sum of 1 / (60 + rank) over the lists it appears in."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def choose_final(
    ranked: list[Candidate], threshold: float, *, minimum: int = MIN_FINAL, maximum: int = MAX_FINAL
) -> list[Candidate]:
    """The best candidates that clear the threshold, but never fewer than `minimum`."""
    above = [c for c in ranked if (c.rerank_score or 0.0) >= threshold]
    kept = above[:maximum]
    if len(kept) < minimum:
        kept = ranked[: min(minimum, maximum)]
    return kept


def join_neighbours(kept: list[Candidate]) -> list[Passage]:
    """Join kept pieces that are next to each other in the same document section."""
    passages: list[tuple[float, Passage]] = []
    by_section: dict[tuple[str, Any], list[Candidate]] = {}
    for candidate in kept:
        if candidate.source_type == "document":
            key = (candidate.source_key, candidate.meta.get("section"))
            by_section.setdefault(key, []).append(candidate)
        else:
            passages.append((candidate.final_rank or 0, _single(candidate)))
    for group in by_section.values():
        group.sort(key=lambda c: c.position)
        run: list[Candidate] = []
        for candidate in group:
            if run and candidate.position != run[-1].position + 1:
                passages.append(_joined(run))
                run = []
            run.append(candidate)
        passages.append(_joined(run))
    passages.sort(key=lambda item: item[0])
    return [passage for _, passage in passages]


def _single(candidate: Candidate) -> Passage:
    return Passage(
        candidate.header,
        candidate.text,
        candidate.source_type,
        candidate.rerank_score or 0.0,
        (candidate.id,),
        candidate.meta,
    )


def _joined(run: list[Candidate]) -> tuple[float, Passage]:
    best = min(run, key=lambda c: c.final_rank or 0)
    text = run[0].text
    for candidate in run[1:]:
        text += "\n" + candidate.text[candidate.meta.get("overlap_chars", 0) :]
    passage = Passage(
        run[0].header,
        text,
        "document",
        max(c.rerank_score or 0.0 for c in run),
        tuple(c.id for c in run),
        run[0].meta,
    )
    return float(best.final_rank or 0), passage


async def search(
    session: AsyncSession,
    space_id: uuid.UUID,
    query: str,
    *,
    embed_query: Callable[[str], Any],
    rerank: Callable[[str, list[str]], Any],
    threshold: float,
    types: set[str] | None = None,
    scope: Scope | None = None,
) -> SearchResult:
    """Run every stage. `embed_query` and `rerank` are blocking and run in worker threads."""
    timings: dict[str, int] = {}
    started = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal started
        now = time.perf_counter()
        timings[name] = round((now - started) * 1000)
        started = now

    version = int(
        await session.scalar(select(Space.index_version).where(Space.id == space_id)) or 0
    )
    vector = await anyio.to_thread.run_sync(embed_query, query)
    lap("embed")
    scope = scope or Scope()
    vector_hits = await _vector_search(session, space_id, vector, types, scope)
    lap("vector")
    rows = await session.scalars(
        select(Chunk.id).where(Chunk.space_id == space_id, *_conditions(types, scope))
    )
    allowed: set[int] | None = set(rows)
    bm25_hits = await _bm25_search(session, space_id, version, query, allowed)
    lap("bm25")

    fused = reciprocal_rank_fusion([i for i, _ in vector_hits], [i for i, _ in bm25_hits])
    order = sorted(fused, key=lambda i: (-fused[i], i))
    ids = order[:RERANK_CANDIDATES]
    rows = (await session.scalars(select(Chunk).where(Chunk.id.in_(order)))).all() if order else []
    by_id = {row.id: row for row in rows}
    order = [i for i in order if i in by_id]  # a chunk may have just been removed
    ids = order[:RERANK_CANDIDATES]
    candidates: dict[int, Candidate] = {}
    for chunk_id in order:
        row = by_id[chunk_id]
        candidates[chunk_id] = Candidate(
            row.id, row.source_type, row.source_key, row.position, row.header, row.text, row.meta
        )
    for rank, (chunk_id, distance) in enumerate(vector_hits, start=1):
        candidates[chunk_id].vector_rank, candidates[chunk_id].vector_distance = rank, distance
    for rank, (chunk_id, score) in enumerate(bm25_hits, start=1):
        candidates[chunk_id].bm25_rank, candidates[chunk_id].bm25_score = rank, score
    for rank, chunk_id in enumerate(order, start=1):
        candidates[chunk_id].fused_rank = rank
        candidates[chunk_id].fused_score = fused[chunk_id]
    lap("fuse")

    scored = [candidates[i] for i in ids]
    scores = await anyio.to_thread.run_sync(
        rerank, query, [f"{c.header}\n{c.text}" for c in scored]
    )
    for candidate, score in zip(scored, scores, strict=True):
        candidate.rerank_score = float(score)
    ranked = sorted(scored, key=lambda c: (-(c.rerank_score or 0.0), c.fused_rank or 0))
    lap("rerank")

    kept = choose_final(ranked, threshold)
    for rank, candidate in enumerate(kept, start=1):
        candidate.final_rank = rank
    passages = join_neighbours(kept)
    lap("join")
    ordered = sorted(
        candidates.values(),
        key=lambda c: (
            c.final_rank is None,
            c.final_rank or 0,
            c.rerank_score is None,
            -(c.rerank_score or 0.0),
            c.fused_rank or 0,
        ),
    )
    return SearchResult(query, ordered, passages, timings)
