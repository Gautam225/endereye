"""Starting points for a conversation: suggested questions, and searching the space."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import KnowledgeItem, Space
from app.schemas.chat import DiscoverHit
from app.services import knowledge
from app.services.spaces import SpaceAccess

FIRST_QUESTION = "What data is available for me to explore?"
MAX_SUGGESTIONS = 6
MAX_HITS = 8
SNIPPET_CHARS = 200
_SHOWN_TYPES = {"table", "column", "glossary", "document", "example_sql"}


async def suggested_questions(session: AsyncSession, space_id: uuid.UUID) -> list[str]:
    """Questions to start with: the ones an editor wrote in About, then the example questions
    (trusted first). Without any written, the first question is "what data is there?"."""
    configured = await session.scalar(select(Space.suggested_questions).where(Space.id == space_id))
    rows = await session.scalars(
        select(KnowledgeItem.title)
        .where(KnowledgeItem.space_id == space_id, KnowledgeItem.kind == "example_sql")
        .order_by(KnowledgeItem.trusted.desc(), KnowledgeItem.created_at)
    )
    questions = list(dict.fromkeys(title for title in rows if title))
    written = list(configured or [])
    lead = written if len(written) >= 2 else [FIRST_QUESTION, *written]
    return list(dict.fromkeys([*lead, *questions]))[:MAX_SUGGESTIONS]


def _title(source_type: str, header: str, meta: dict) -> str:
    if source_type == "table":
        return str(meta.get("table", header))
    if source_type == "example_sql":
        return str(meta.get("question", header))
    if source_type == "glossary":
        return str(meta.get("term", header))
    return header


async def discover(
    session: AsyncSession, access: SpaceAccess, query: str, settings: Settings
) -> list[DiscoverHit]:
    result = await knowledge.search(session, access, query, settings)
    hits: list[DiscoverHit] = []
    seen: set[tuple[str, str]] = set()
    for passage in result.passages:
        if passage.source_type not in _SHOWN_TYPES:
            continue
        title = _title(passage.source_type, passage.header, passage.meta)
        if (passage.source_type, title) in seen:
            continue
        seen.add((passage.source_type, title))
        snippet = " ".join(passage.text.split())
        hits.append(
            DiscoverHit(
                type=passage.source_type,  # type: ignore[arg-type]
                title=title,
                snippet=snippet
                if len(snippet) <= SNIPPET_CHARS
                else snippet[: SNIPPET_CHARS - 1] + "…",
            )
        )
    return hits[:MAX_HITS]
