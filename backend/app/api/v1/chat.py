"""Chat: threads, asking a question (streamed), stopping it, and downloading the result.

Anyone who can see a space can ask questions in it (viewers included). A thread is private to
the person who started it.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.deps import CurrentUser, SettingsDep
from app.chat.pipeline import run_turn
from app.db.models import User
from app.db.session import SessionDep
from app.llm.gateway import LLMDep
from app.schemas.chat import (
    ChartUpdate,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    DiscoverHit,
    FeedbackIn,
    ForkRequest,
    MessageCreate,
    MessageOut,
    SharedConversationOut,
)
from app.schemas.knowledge import DocumentOut
from app.schemas.spaces import SpaceOut
from app.services import conversations as service
from app.services import discovery, knowledge, spaces

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spaces/{space_id}/conversations", tags=["chat"])
general_router = APIRouter(prefix="/chat", tags=["chat"])
space_router = APIRouter(prefix="/spaces/{space_id}", tags=["chat"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=200, description="Search titles and questions")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ConversationOut]:
    """Your conversations in this space, most recent first."""
    access = await spaces.get_access(session, user, space_id)
    found = await service.list_conversations(session, access, user, q, limit)
    return [ConversationOut.model_validate(c) for c in found]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    space_id: uuid.UUID, body: ConversationCreate, user: CurrentUser, session: SessionDep
) -> ConversationOut:
    access = await spaces.get_access(session, user, space_id)
    return ConversationOut.model_validate(
        await service.create_conversation(session, access, user, body.title)
    )


@router.get("/shared", response_model=list[SharedConversationOut])
async def list_shared(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[SharedConversationOut]:
    """Chats other members of this space shared (read-only)."""
    access = await spaces.get_access(session, user, space_id)
    found = await service.list_shared(session, access, user, 50)
    return [
        SharedConversationOut(id=c.id, title=c.title, owner_name=name, updated_at=c.updated_at)
        for c, name in found
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    space_id: uuid.UUID, conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ConversationDetail:
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_readable_conversation(session, access, user, conversation_id)
    messages = await service.list_messages(session, conversation.id)
    mine = conversation.user_id == user.id
    owner = None if mine else await session.get(User, conversation.user_id)
    return ConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
        mine=mine,
        owner_name=owner.full_name if owner else None,
    )


@router.post(
    "/{conversation_id}/fork", response_model=ConversationOut, status_code=status.HTTP_201_CREATED
)
async def fork_conversation(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: ForkRequest,
    user: CurrentUser,
    session: SessionDep,
) -> ConversationOut:
    """Branch a chat (yours, or one shared with you) into a new chat of your own."""
    access = await spaces.get_access(session, user, space_id)
    source = await service.get_readable_conversation(session, access, user, conversation_id)
    return ConversationOut.model_validate(
        await service.fork_conversation(session, access, user, source, body.message_id)
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> ConversationOut:
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    return ConversationOut.model_validate(
        await service.update_conversation(
            session, conversation, body.title, body.pinned, body.shared
        )
    )


@router.delete("/{conversation_id}", status_code=NO_CONTENT)
async def delete_conversation(
    space_id: uuid.UUID, conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    await service.delete_conversation(session, conversation)
    return Response(status_code=NO_CONTENT)


# ── Asking ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    space_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    seq: int


async def prepare_turn(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: MessageCreate,
    user: CurrentUser,
    session: SessionDep,
) -> PreparedTurn:
    """Checks access and creates the message before streaming starts, so problems (not a
    member, not your conversation, an answer already running) are normal HTTP errors."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    mentions = await service.resolve_mentions(session, conversation, body.mentions)
    message = await service.start_turn(
        session, conversation, body.question, body.replace_message_id, mentions, body.mode
    )
    return PreparedTurn(space_id, conversation.id, message.id, message.seq)


PreparedDep = Annotated[PreparedTurn, Depends(prepare_turn)]


@router.post("/{conversation_id}/messages", response_class=EventSourceResponse)
async def ask(
    prepared: PreparedDep, request: Request, settings: SettingsDep, llm: LLMDep
) -> AsyncIterator[ServerSentEvent]:
    """Ask a question. The answer streams as events: start, status, sql, rows, answer, error,
    done. `done` carries the finished message. The turn runs on the server on its own: closing
    the connection (a refresh, a lost network) does not stop it. Reconnect with `.../events`,
    or stop it with `.../cancel`."""
    channel = service.runs.start(prepared.message_id)

    async def drive() -> None:
        try:
            await channel.publish(
                "start",
                {
                    "conversation_id": str(prepared.conversation_id),
                    "message_id": str(prepared.message_id),
                    "seq": prepared.seq,
                },
            )
            async for name, data in run_turn(
                sessionmaker=request.app.state.sessionmaker,
                settings=settings,
                llm=llm,
                space_id=prepared.space_id,
                message_id=prepared.message_id,
                cancel=channel.token,
            ):
                await channel.publish(name, data)
        finally:
            await channel.close()
            service.runs.finish(prepared.message_id)

    tasks: set[asyncio.Task] = request.app.state.chat_tasks
    task = asyncio.create_task(drive())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    async for name, data in channel.follow():
        yield ServerSentEvent(event=name, data=data)


@dataclass(frozen=True, slots=True)
class Following:
    message_id: uuid.UUID
    finished: dict | None  # the stored message, when no turn is running for it any more


async def prepare_follow(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Following:
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    if service.runs.get(message.id) is not None:
        return Following(message.id, None)
    if message.status == "running":
        await service.expire_lost_turn(session, message)  # the server restarted under it
    return Following(message.id, MessageOut.model_validate(message).model_dump(mode="json"))


FollowingDep = Annotated[Following, Depends(prepare_follow)]


@router.get("/{conversation_id}/messages/{message_id}/events", response_class=EventSourceResponse)
async def follow_turn(following: FollowingDep) -> AsyncIterator[ServerSentEvent]:
    """Rejoin an answer that is still being written (after a refresh): every event so far, then
    the rest. When the answer already ended, just `done` with the stored message."""
    if following.finished is not None:
        yield ServerSentEvent(event="done", data=following.finished)
        return
    channel = service.runs.get(following.message_id)
    if channel is None:  # it ended between the check and now
        return
    async for name, data in channel.follow():
        yield ServerSentEvent(event=name, data=data)


@router.post("/{conversation_id}/messages/{message_id}/cancel", status_code=NO_CONTENT)
async def cancel_turn(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    """Stop an answer that is still being written. Safe to call when it already finished."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    service.runs.stop(message.id)
    return Response(status_code=NO_CONTENT)


@router.get("/{conversation_id}/messages/{message_id}/csv")
async def download_csv(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """The full result as CSV: the query runs again, so every row is included (up to the
    query row limit). Cells that look like formulas are neutralised."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    content = await service.result_csv(session, access, message, settings)
    name = service.file_name(conversation.title)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{conversation_id}/messages/{message_id}/xlsx")
async def download_xlsx(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """The full result as an Excel workbook, with the answer and the SQL on a second sheet."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    content = await service.result_xlsx(session, access, conversation, message, settings)
    name = service.file_name(conversation.title, "xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.put("/{conversation_id}/messages/{message_id}/feedback", response_model=MessageOut)
async def give_feedback(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: FeedbackIn,
    user: CurrentUser,
    session: SessionDep,
) -> MessageOut:
    """Thumbs up or down, with an optional comment. It is a signal for the people who
    maintain the space; it never changes how questions are answered by itself."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    return MessageOut.model_validate(
        await service.set_feedback(session, message, body.rating, body.comment)
    )


@router.delete("/{conversation_id}/messages/{message_id}/feedback", response_model=MessageOut)
async def clear_feedback(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> MessageOut:
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    return MessageOut.model_validate(await service.set_feedback(session, message, None))


@router.put("/{conversation_id}/messages/{message_id}/chart", response_model=MessageOut)
async def edit_chart(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: ChartUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> MessageOut:
    """Change an answer's chart: its type, axes, series and title."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    message = await service.get_message(session, conversation, message_id)
    return MessageOut.model_validate(await service.set_chart(session, message, body.model_dump()))


# ── Documents added in a chat ────────────────────────────────────────────────


@router.get("/{conversation_id}/documents", response_model=list[DocumentOut])
async def list_chat_documents(
    space_id: uuid.UUID, conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[DocumentOut]:
    """The files added to this conversation (and only this one)."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    return [
        DocumentOut.model_validate(d)
        for d in await service.list_chat_documents(session, conversation)
    ]


@router.post(
    "/{conversation_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED
)
async def add_chat_document(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[
        UploadFile, File(description="PDF, Word, PowerPoint, Excel, HTML, Markdown or text")
    ],
) -> DocumentOut:
    """Add a file to this conversation. Only you, in this conversation, can ask about it.
    Anyone who can ask questions in the space can do this; it changes nothing else."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    document = await service.add_chat_document(session, access, user, conversation, file, settings)
    knowledge.schedule_indexing(
        request.app.state.sessionmaker, request.app.state.index_tasks, document.id, settings
    )
    return DocumentOut.model_validate(document)


@router.delete("/{conversation_id}/documents/{document_id}", status_code=NO_CONTENT)
async def delete_chat_document(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    document_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    access = await spaces.get_access(session, user, space_id)
    conversation = await service.get_conversation(session, access, user, conversation_id)
    await service.delete_chat_document(session, access, conversation, document_id)
    return Response(status_code=NO_CONTENT)


# ── The general chat ─────────────────────────────────────────────────────────


@general_router.post("/general", response_model=SpaceOut)
async def general_chat_space(user: CurrentUser, session: SessionDep) -> SpaceOut:
    """The space behind your general chat (no tables; add documents to a chat to ask about
    them). Made the first time it is needed."""
    space = await spaces.personal_space(session, user)
    access = await spaces.get_access(session, user, space.id)
    return await spaces.get_space(session, access)


# ── Starting points ──────────────────────────────────────────────────────────


@space_router.get("/suggestions", response_model=list[str])
async def suggested_questions(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[str]:
    """Questions to start a new conversation with."""
    await spaces.get_access(session, user, space_id)
    return await discovery.suggested_questions(session, space_id)


@space_router.get("/discover", response_model=list[DiscoverHit])
async def discover(
    space_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=1, max_length=300)],
) -> list[DiscoverHit]:
    """Find tables, columns, terms, documents and example questions in the space."""
    access = await spaces.get_access(session, user, space_id)
    return await discovery.discover(session, access, q.strip(), settings)
