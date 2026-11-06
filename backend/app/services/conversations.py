"""Chat threads and their messages. A thread belongs to the person who started it.

Nobody else can read it, and the assistant only ever sees the earlier turns of the same
thread, so one conversation's context can't leak into another.
"""

import asyncio
import csv
import io
import re
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from fastapi import UploadFile
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.chat.charts import ChartError, validate_chart
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    Conversation,
    Document,
    Message,
    MessageStatus,
    Space,
    SpaceAccessRule,
    SpaceTable,
    User,
)
from app.engine.duckdb_engine import CancelToken
from app.services import knowledge, spaces
from app.services.spaces import SpaceAccess


def table_mention(name: str) -> str:
    """What to type after @ to point at a table: its name with spaces and symbols as underscores."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "table"


NEW_CHAT = "New chat"
TITLE_CHARS = 60
STALE_AFTER = timedelta(minutes=5)  # a turn that has been "running" this long was lost


KEEP_FINISHED_FOR = 60.0  # seconds a finished turn's events stay available to a late reader


class TurnChannel:
    """The events of one running turn. The turn writes here, not to a connection, so a refreshed
    or dropped page can reconnect and replay everything from the start."""

    def __init__(self) -> None:
        self.token = CancelToken()
        self.events: list[tuple[str, dict]] = []
        self.finished = False
        self._changed = asyncio.Condition()

    async def publish(self, name: str, data: dict) -> None:
        async with self._changed:
            self.events.append((name, data))
            self._changed.notify_all()

    async def close(self) -> None:
        async with self._changed:
            self.finished = True
            self._changed.notify_all()

    async def follow(self) -> AsyncIterator[tuple[str, dict]]:
        """Every event so far, then new ones as they come, until the turn ends."""
        seen = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(
                    lambda seen=seen: seen < len(self.events) or self.finished
                )
                batch = self.events[seen:]
                seen += len(batch)
                done = self.finished
            for event in batch:
                yield event
            if done and not batch:
                return


class Runs:
    """Turns that are running right now, so Stop can reach them and a reconnecting page can
    follow them."""

    def __init__(self) -> None:
        self._channels: dict[uuid.UUID, TurnChannel] = {}
        self._lock = threading.Lock()

    def start(self, message_id: uuid.UUID) -> TurnChannel:
        channel = TurnChannel()
        with self._lock:
            self._channels[message_id] = channel
        return channel

    def get(self, message_id: uuid.UUID) -> TurnChannel | None:
        with self._lock:
            return self._channels.get(message_id)

    def finish(self, message_id: uuid.UUID) -> None:
        """The turn is over. Its events stay for a moment for a page that reconnects just now."""
        with self._lock:
            channel = self._channels.get(message_id)
        if channel is None:
            return

        def forget() -> None:
            with self._lock:
                if self._channels.get(message_id) is channel:
                    del self._channels[message_id]

        asyncio.get_running_loop().call_later(KEEP_FINISHED_FOR, forget)

    def stop(self, message_id: uuid.UUID) -> bool:
        with self._lock:
            channel = self._channels.get(message_id)
        if channel is None or channel.finished:
            return False
        channel.token.cancel()
        return True


runs = Runs()


# ── Threads ──────────────────────────────────────────────────────────────────


async def get_conversation(
    session: AsyncSession, access: SpaceAccess, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if (
        conversation is None
        or conversation.space_id != access.space.id
        or conversation.user_id != user.id
    ):
        raise NotFoundError("That conversation does not exist.")
    return conversation


async def _has_access_rules(session: AsyncSession, space_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(SpaceAccessRule)
            .where(SpaceAccessRule.space_id == space_id)
        )
    )


async def get_readable_conversation(
    session: AsyncSession, access: SpaceAccess, user: User, conversation_id: uuid.UUID
) -> Conversation:
    """One of your own chats, or one another member shared. A shared chat holds results that were
    read under its owner's permissions, so it stops being readable the moment the space has any
    access rule: what one person may see another may not."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.space_id != access.space.id:
        raise NotFoundError("That conversation does not exist.")
    if conversation.user_id == user.id:
        return conversation
    if not conversation.shared or await _has_access_rules(session, access.space.id):
        raise NotFoundError("That conversation does not exist.")
    return conversation


async def list_shared(
    session: AsyncSession, access: SpaceAccess, user: User, limit: int
) -> list[tuple[Conversation, str]]:
    """Chats other members shared in this space (none while the space has access rules)."""
    if await _has_access_rules(session, access.space.id):
        return []
    rows = await session.execute(
        select(Conversation, User.full_name)
        .join(User, User.id == Conversation.user_id)
        .where(
            Conversation.space_id == access.space.id,
            Conversation.shared.is_(True),
            Conversation.user_id != user.id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return [(c, name) for c, name in rows.all()]


_COPIED = (
    "question", "standalone_question", "status", "sql", "trusted", "answer", "assumptions",
    "columns", "rows", "row_count", "truncated", "sources", "citations", "chart", "suggestions",
    "options", "mode", "steps", "error_code", "error", "attempts", "timings", "models", "figures",
    "thoughts", "finished_at",
)  # fmt: skip


async def fork_conversation(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    source: Conversation,
    message_id: uuid.UUID | None,
) -> Conversation:
    """A new chat of your own that starts as a copy of this one, up to and including an answer.
    The copy has the answers and their results as they were; feedback and reviews stay behind."""
    messages = await list_messages(session, source.id)
    if message_id is not None:
        target = next((m for m in messages if m.id == message_id), None)
        if target is None:
            raise NotFoundError("That message does not exist in this conversation.")
        messages = [m for m in messages if m.seq <= target.seq]
    branch = Conversation(
        space_id=access.space.id, user_id=user.id, title=f"{source.title} (branch)"[:200]
    )
    session.add(branch)
    await session.flush()
    for original in messages:
        if original.status == MessageStatus.RUNNING.value:
            continue
        session.add(
            Message(
                conversation_id=branch.id,
                seq=original.seq,
                mentions=[],
                **{name: getattr(original, name) for name in _COPIED},
            )
        )
    await session.commit()
    return branch


async def list_conversations(
    session: AsyncSession, access: SpaceAccess, user: User, query: str | None, limit: int
) -> list[Conversation]:
    statement = select(Conversation).where(
        Conversation.space_id == access.space.id, Conversation.user_id == user.id
    )
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        in_messages = select(Message.conversation_id).where(
            Message.question.ilike(pattern, escape="\\")
        )
        statement = statement.where(
            or_(Conversation.title.ilike(pattern, escape="\\"), Conversation.id.in_(in_messages))
        )
    return list(
        await session.scalars(
            statement.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(
                limit
            )
        )
    )


async def create_conversation(
    session: AsyncSession, access: SpaceAccess, user: User, title: str | None
) -> Conversation:
    conversation = Conversation(space_id=access.space.id, user_id=user.id, title=title or NEW_CHAT)
    session.add(conversation)
    await session.commit()
    return conversation


async def update_conversation(
    session: AsyncSession,
    conversation: Conversation,
    title: str | None,
    pinned: bool | None,
    shared: bool | None = None,
) -> Conversation:
    if title is not None:
        conversation.title = title
    if shared is not None:
        if shared and await _has_access_rules(session, conversation.space_id):
            raise ConflictError(
                "This space has access rules, so chats can't be shared in it: what one person "
                "may see, another may not.",
                code="sharing_blocked",
            )
        conversation.shared = shared
    if pinned is not None:
        conversation.pinned = pinned
    # Renaming or pinning is not new activity: the chat keeps its place among the recent ones.
    flag_modified(conversation, "updated_at")
    await session.commit()
    return conversation


MAX_CHAT_DOCUMENTS = 10


async def delete_conversation(session: AsyncSession, conversation: Conversation) -> None:
    documents = list(
        await session.scalars(select(Document).where(Document.conversation_id == conversation.id))
    )
    paths = [Path(d.storage_path) for d in documents]
    await session.delete(conversation)  # its messages, documents and their chunks go with it
    if documents:
        # Keyword indexes are rebuilt when this number moves on.
        await session.execute(
            update(Space)
            .where(Space.id == conversation.space_id)
            .values(index_version=Space.index_version + 1)
        )
    await session.commit()
    for path in paths:
        await anyio.Path(path).unlink(missing_ok=True)


async def list_chat_documents(session: AsyncSession, conversation: Conversation) -> list[Document]:
    return await knowledge.list_documents(session, conversation.space_id, conversation.id)


async def add_chat_document(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    conversation: Conversation,
    upload: UploadFile,
    settings: Settings,
) -> Document:
    """Add a file to this conversation only. Other chats, and the space, never see it."""
    existing = await list_chat_documents(session, conversation)
    if len(existing) >= MAX_CHAT_DOCUMENTS:
        raise AppError(
            f"A conversation can have at most {MAX_CHAT_DOCUMENTS} documents.",
            code="too_many_documents",
        )
    return await knowledge.add_document(
        session, access, user, upload, settings, conversation_id=conversation.id
    )


async def delete_chat_document(
    session: AsyncSession, access: SpaceAccess, conversation: Conversation, document_id: uuid.UUID
) -> None:
    await knowledge.delete_document(session, access, document_id, conversation.id)


async def resolve_mentions(
    session: AsyncSession, conversation: Conversation, ids: list[uuid.UUID]
) -> list[dict[str, str]]:
    """What a question points at with @: documents (the space's, or this conversation's own) and
    tables of the space. Each is {"id", "name", "kind"}."""
    if not ids:
        return []
    found = await session.scalars(
        select(Document).where(
            Document.id.in_(ids),
            Document.space_id == conversation.space_id,
            or_(Document.conversation_id.is_(None), Document.conversation_id == conversation.id),
        )
    )
    documents = {d.id: d for d in found}
    rest = [i for i in ids if i not in documents]
    tables = {}
    if rest:
        rows = await session.scalars(
            select(SpaceTable).where(
                SpaceTable.id.in_(rest), SpaceTable.space_id == conversation.space_id
            )
        )
        tables = {t.id: t for t in rows}
    if any(i not in documents and i not in tables for i in ids):
        raise NotFoundError("One of the things you mentioned does not exist.")
    return [
        {"id": str(i), "name": documents[i].mention, "kind": "document"}
        if i in documents
        else {"id": str(i), "name": table_mention(tables[i].name), "kind": "table"}
        for i in dict.fromkeys(ids)
    ]


async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    return list(
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
        )
    )


# ── Turns ────────────────────────────────────────────────────────────────────


async def start_turn(
    session: AsyncSession,
    conversation: Conversation,
    question: str,
    replace_message_id: uuid.UUID | None,
    mentions: list[dict[str, str]] | None = None,
    mode: str = "standard",
) -> Message:
    """Create the message for a new question (or an edited one) and mark it running."""
    if replace_message_id is not None:
        target = await session.get(Message, replace_message_id)
        if target is None or target.conversation_id != conversation.id:
            raise NotFoundError("That message does not exist in this conversation.")
        # Editing a question replaces it and everything that followed.
        await session.execute(
            delete(Message).where(
                Message.conversation_id == conversation.id, Message.seq >= target.seq
            )
        )

    await _expire_lost_turns(session, conversation.id)
    running = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.status == MessageStatus.RUNNING.value,
        )
    )
    if running:
        await session.rollback()
        raise ConflictError(
            "An answer is still being written. Wait for it, or stop it first.",
            code="turn_running",
        )

    last = await session.scalar(
        select(func.max(Message.seq)).where(Message.conversation_id == conversation.id)
    )
    message = Message(
        conversation_id=conversation.id,
        seq=(last or 0) + 1,
        question=question,
        mentions=mentions or [],
        mode=mode,
        status=MessageStatus.RUNNING.value,
    )
    session.add(message)
    if conversation.title == NEW_CHAT:
        conversation.title = title_from(question)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    return message


async def expire_lost_turn(session: AsyncSession, message: Message) -> None:
    """A message left 'running' with no turn behind it (the server restarted): end it honestly."""
    message.status = MessageStatus.FAILED.value
    message.error_code = "lost"
    message.error = "This answer was interrupted."
    message.finished_at = datetime.now(UTC)
    await session.commit()


async def _expire_lost_turns(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    stale = await session.scalars(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.status == MessageStatus.RUNNING.value,
            Message.created_at < datetime.now(UTC) - STALE_AFTER,
        )
    )
    for message in stale:
        message.status = MessageStatus.FAILED.value
        message.error_code = "lost"
        message.error = "This answer was interrupted."
        message.finished_at = datetime.now(UTC)


_TITLE_BREAKS = re.compile(
    r"(?<=\w)[.?!:;,]\s|\s(?:using|with|based on|that|which|for each|where)\s", re.I
)


def title_from(question: str) -> str:
    """A short title from the question: its first clause, cut at a word, never a whole paragraph."""
    text = " ".join(question.split())
    clause = _TITLE_BREAKS.split(text, maxsplit=1)[0].rstrip(" .?!:;,")
    text = clause if len(clause) >= 12 else text
    if len(text) <= TITLE_CHARS:
        return text
    cut = text[: TITLE_CHARS - 1].rsplit(" ", 1)[0] or text[: TITLE_CHARS - 1]
    return cut.rstrip(" .,;:") + "…"


async def get_message(
    session: AsyncSession, conversation: Conversation, message_id: uuid.UUID
) -> Message:
    message = await session.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id:
        raise NotFoundError("That message does not exist in this conversation.")
    return message


# ── CSV ──────────────────────────────────────────────────────────────────────

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> object:
    """Stop spreadsheet programs from running a cell as a formula (CSV injection)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return "" if value is None else value


def to_csv(columns: list[str], rows: list[list[object]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([csv_cell(c) for c in columns])
    for row in rows:
        writer.writerow([csv_cell(v) for v in row])
    return out.getvalue()


def file_name(title: str, extension: str = "csv") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return f"{slug or 'results'}.{extension}"


MAX_SHEET_WIDTH = 60


def to_xlsx(
    columns: list[str],
    rows: list[list[object]],
    summary: list[tuple[str, str]],
) -> bytes:
    """A workbook: the result on one sheet (a bold, frozen header row and columns wide enough
    to read) and what the answer said on another. Text that looks like a formula is neutralised,
    as in the CSV."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Results"
    sheet.append([csv_cell(c) for c in columns])
    for row in rows:
        sheet.append([csv_cell(v) if isinstance(v, str) or v is None else v for v in row])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for index, name in enumerate(columns, start=1):
        longest = max([len(str(name))] + [len(str(r[index - 1])) for r in rows[:200]])
        sheet.column_dimensions[get_column_letter(index)].width = min(MAX_SHEET_WIDTH, longest + 2)

    about = book.create_sheet("About")
    for label, text in summary:
        about.append([label, csv_cell(text)])
    about.column_dimensions["A"].width = 18
    about.column_dimensions["B"].width = 100
    for line in about.iter_rows():
        line[0].font = Font(bold=True)
        line[1].alignment = Alignment(wrap_text=True, vertical="top")
        line[0].alignment = Alignment(vertical="top")
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


async def result_xlsx(
    session: AsyncSession,
    access: SpaceAccess,
    conversation: Conversation,
    message: Message,
    settings: Settings,
) -> bytes:
    """The full result (the query runs again, as for CSV) with the question, the answer, the
    overall figures and the SQL on a second sheet."""
    if not message.sql:
        raise NotFoundError("This answer has no query result to download.")
    result = await spaces.run_sql(session, access, message.sql, settings)
    totals = [f"{t['name']}: {t['value']:,}" for t in ((message.chart or {}).get("totals") or [])]
    summary = [
        ("Chat", conversation.title),
        ("Question", message.question),
        ("Answer", message.answer or ""),
        ("Overall figures", "\n".join(totals)),
        (
            "Rows",
            f"{len(result.rows):,}" + (" (the row limit was reached)" if result.truncated else ""),
        ),
        ("SQL", message.sql),
        ("Exported", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    return to_xlsx([c.name for c in result.columns], result.rows, [s for s in summary if s[1]])


async def result_csv(
    session: AsyncSession, access: SpaceAccess, message: Message, settings: Settings
) -> str:
    """Run the message's SQL again (so the file has every row, up to the limit) as CSV."""
    if not message.sql:
        raise NotFoundError("This answer has no query result to download.")
    result = await spaces.run_sql(session, access, message.sql, settings)
    return to_csv([c.name for c in result.columns], result.rows)


async def set_feedback(
    session: AsyncSession, message: Message, rating: str | None, comment: str = ""
) -> Message:
    """Record (or clear, with rating None) what the asker thought of an answer."""
    if message.status == MessageStatus.RUNNING.value:
        raise ConflictError("Wait for the answer to finish first.", code="turn_running")
    message.feedback = rating
    message.feedback_comment = (comment or None) if rating else None
    message.feedback_at = datetime.now(UTC) if rating else None
    await session.commit()
    return message


async def set_chart(session: AsyncSession, message: Message, spec: dict) -> Message:
    """Save a chart a person edited (type, axes, title) for this answer."""
    if not message.columns or not message.rows:
        raise AppError("This answer has no result to chart.", code="no_result")
    try:
        chart = validate_chart(spec, message.columns)
    except ChartError as exc:
        raise AppError(str(exc), code="invalid_chart") from None
    chart["partial"] = (message.row_count or 0) > len(message.rows) or message.truncated
    message.chart = chart
    await session.commit()
    return message
