"""Chats shared with chosen people, the inbox of what was shared with you, and opening a
document that a chat cites."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser
from app.core.errors import NotFoundError
from app.db.models import Conversation, Document, Space, User
from app.db.session import SessionDep
from app.schemas.chat import ConversationOut, MessageOut
from app.schemas.knowledge import DocumentOut
from app.schemas.sharing import (
    BranchOut,
    InboxItem,
    SharedChat,
    SharePerson,
    SharesIn,
    SharesOut,
    UnreadOut,
)
from app.schemas.spaces import UserBrief
from app.services import conversations as conversation_service
from app.services import sharing, spaces

router = APIRouter(tags=["sharing"])

PDF = "application/pdf"
# Opened in the page, like a PDF; every other kind of file downloads.
IMAGES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


# ── The owner ────────────────────────────────────────────────────────────────


async def _shares_out(session: SessionDep, conversation: Conversation) -> SharesOut:
    return SharesOut(
        people=[
            SharePerson(id=p.id, full_name=p.full_name, email=p.email, seen_at=p.seen_at)
            for p in await sharing.people(session, conversation)
        ],
        everyone=conversation.shared,
    )


@router.get("/spaces/{space_id}/conversations/{conversation_id}/shares", response_model=SharesOut)
async def get_shares(
    space_id: uuid.UUID, conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> SharesOut:
    """Who your chat is shared with."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await conversation_service.get_conversation(
        session, access, user, conversation_id
    )
    return await _shares_out(session, conversation)


@router.put("/spaces/{space_id}/conversations/{conversation_id}/shares", response_model=SharesOut)
async def set_shares(
    space_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: SharesIn,
    user: CurrentUser,
    session: SessionDep,
) -> SharesOut:
    """Choose who can read your chat. People you leave out lose access."""
    access = await spaces.get_access(session, user, space_id)
    conversation = await conversation_service.get_conversation(
        session, access, user, conversation_id
    )
    await sharing.set_people(session, user, conversation, body.user_ids)
    return await _shares_out(session, conversation)


@router.get("/people", response_model=list[UserBrief])
async def find_people(
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[UserBrief]:
    """Active people to share a chat with, found by name or email."""
    statement = select(User).where(User.is_active.is_(True), User.id != user.id)
    needle = q.strip().lower()
    if needle:
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(
            func.lower(User.full_name).like(pattern, escape="\\")
            | func.lower(User.email).like(pattern, escape="\\")
        )
    rows = await session.scalars(statement.order_by(func.lower(User.full_name)).limit(20))
    return [UserBrief.model_validate(u) for u in rows]


# ── The reader ───────────────────────────────────────────────────────────────


@router.get("/shared-chats", response_model=list[InboxItem])
async def shared_with_me(user: CurrentUser, session: SessionDep) -> list[InboxItem]:
    return [
        InboxItem(
            id=i.conversation.id,
            space_id=i.conversation.space_id,
            title=i.conversation.title,
            owner_name=i.owner_name,
            space_name=i.space_name,
            personal=i.personal,
            shared_at=i.shared_at,
            updated_at=i.conversation.updated_at,
            unread=i.unread,
        )
        for i in await sharing.inbox(session, user)
    ]


@router.get("/shared-chats/unread", response_model=UnreadOut)
async def unread(user: CurrentUser, session: SessionDep) -> UnreadOut:
    return UnreadOut(count=await sharing.unread_count(session, user))


@router.get("/shared-chats/{conversation_id}", response_model=SharedChat)
async def open_shared(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> SharedChat:
    """A chat someone shared with you, read-only."""
    conversation = await sharing.get_shared(session, user, conversation_id)
    space = await session.get(Space, conversation.space_id)
    owner = await session.get(User, conversation.user_id)
    messages = await sharing.messages(session, conversation)
    personal = space is None or space.is_personal
    return SharedChat(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
        mine=False,
        owner_name=owner.full_name if owner else None,
        space_id=conversation.space_id,
        space_name="General chat" if personal or space is None else space.name,
        personal=personal,
    )


@router.get("/shared-chats/{conversation_id}/documents", response_model=list[DocumentOut])
async def shared_documents(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[DocumentOut]:
    """The files added to a chat shared with you."""
    conversation = await sharing.get_shared(session, user, conversation_id)
    found = await conversation_service.list_chat_documents(session, conversation)
    return [DocumentOut.model_validate(d) for d in found]


@router.post("/shared-chats/{conversation_id}/branch", response_model=BranchOut)
async def branch_shared(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> BranchOut:
    """Copy a shared chat into a chat of your own (in your General chat), to carry on from."""
    source = await sharing.get_shared(session, user, conversation_id)
    own = await spaces.personal_space(session, user)
    access = await spaces.get_access(session, user, own.id)
    branch = await conversation_service.fork_conversation(session, access, user, source, None)
    return BranchOut(**ConversationOut.model_validate(branch).model_dump(), space_id=own.id)


# ── Documents ────────────────────────────────────────────────────────────────


@router.get("/documents/{document_id}/file")
async def document_file(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> FileResponse:
    """The original file: a PDF opens in the page, anything else downloads. Allowed for people in
    the document's space, and for the people a chat that cites it is shared with."""
    document = await session.get(Document, document_id)
    if document is None or not await sharing.can_read_document(session, user, document):
        raise NotFoundError("That document does not exist.")
    name = document.filename.lower()
    shown = PDF if name.endswith(".pdf") else IMAGES.get(name[name.rfind(".") :])
    return FileResponse(
        document.storage_path,
        media_type=shown or "application/octet-stream",
        filename=document.filename,
        content_disposition_type="inline" if shown else "attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
