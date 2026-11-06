"""Sharing a chat with chosen people, and what they can then open.

A shared chat is read-only for the people it is shared with. They can branch a copy of their own
and open the documents it cites. In a space with access rules a chat can't be shared, because its
results were read under its owner's permissions (a person's own General chat has no such rules).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.models import (
    Conversation,
    ConversationShare,
    Document,
    Message,
    Space,
    SpaceAccessRule,
    SpaceMember,
    User,
)
from app.db.models.user import Role
from app.services import notifications

MAX_PEOPLE = 50


@dataclass(frozen=True, slots=True)
class Person:
    id: uuid.UUID
    full_name: str
    email: str
    seen_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Inbox:
    conversation: Conversation
    owner_name: str
    space_name: str
    personal: bool
    shared_at: datetime
    unread: bool


# ── The owner's side ─────────────────────────────────────────────────────────


async def _has_access_rules(session: AsyncSession, space_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(SpaceAccessRule)
            .where(SpaceAccessRule.space_id == space_id)
        )
    )


async def people(session: AsyncSession, conversation: Conversation) -> list[Person]:
    rows = await session.execute(
        select(User.id, User.full_name, User.email, ConversationShare.seen_at)
        .join(ConversationShare, ConversationShare.user_id == User.id)
        .where(ConversationShare.conversation_id == conversation.id)
        .order_by(func.lower(User.full_name))
    )
    return [Person(*row) for row in rows.all()]


async def set_people(
    session: AsyncSession, owner: User, conversation: Conversation, user_ids: list[uuid.UUID]
) -> list[Person]:
    """Replace who this chat is shared with. New people are told; people taken off lose it."""
    wanted = {u for u in user_ids if u != owner.id}
    if len(wanted) > MAX_PEOPLE:
        raise ConflictError(f"A chat can be shared with at most {MAX_PEOPLE} people.")
    if wanted and await _has_access_rules(session, conversation.space_id):
        space = await session.get(Space, conversation.space_id)
        if space is None or not space.is_personal:
            raise ConflictError(
                "This space has access rules, so chats can't be shared in it: what one person "
                "may see, another may not.",
                code="sharing_blocked",
            )
    if wanted:
        found = set(
            await session.scalars(
                select(User.id).where(User.id.in_(wanted), User.is_active.is_(True))
            )
        )
        if found != wanted:
            raise NotFoundError("One of those people could not be found.")
    current = set(
        await session.scalars(
            select(ConversationShare.user_id).where(
                ConversationShare.conversation_id == conversation.id
            )
        )
    )
    removed = current - wanted
    added = wanted - current
    if removed:
        await session.execute(
            delete(ConversationShare).where(
                ConversationShare.conversation_id == conversation.id,
                ConversationShare.user_id.in_(removed),
            )
        )
    for user_id in added:
        session.add(ConversationShare(conversation_id=conversation.id, user_id=user_id))
    await session.commit()
    if added:
        await notifications.notify(
            session,
            list(added),
            kind="chat_shared",
            level="info",
            title=f"{owner.full_name} shared a chat with you",
            body=conversation.title,
            link=f"/shared/{conversation.id}",
        )
    return await people(session, conversation)


# ── The reader's side ────────────────────────────────────────────────────────


async def _shared_with_everyone(
    session: AsyncSession, user: User, conversation: Conversation
) -> bool:
    """The older kind of sharing: every member of the space, while it has no access rules."""
    if not conversation.shared:
        return False
    member = user.role == Role.ADMIN or await session.get(
        SpaceMember, (conversation.space_id, user.id)
    )
    return bool(member) and not await _has_access_rules(session, conversation.space_id)


async def can_read(session: AsyncSession, user: User, conversation: Conversation) -> bool:
    if conversation.user_id == user.id:
        return True
    if await session.get(ConversationShare, (conversation.id, user.id)):
        return True
    return await _shared_with_everyone(session, user, conversation)


async def get_shared(session: AsyncSession, user: User, conversation_id: uuid.UUID) -> Conversation:
    """A chat someone else shared with you. Opening it is what marks it as seen."""
    conversation = await session.get(Conversation, conversation_id)
    if (
        conversation is None
        or conversation.user_id == user.id
        or not await can_read(session, user, conversation)
    ):
        raise NotFoundError("That chat is not shared with you, or no longer is.")
    await session.execute(
        update(ConversationShare)
        .where(
            ConversationShare.conversation_id == conversation.id,
            ConversationShare.user_id == user.id,
            ConversationShare.seen_at.is_(None),
        )
        .values(seen_at=datetime.now(UTC))
    )
    await session.commit()
    return conversation


async def inbox(session: AsyncSession, user: User, limit: int = 100) -> list[Inbox]:
    """Chats shared with you: by name, and (older kind) with everyone in a space you are in."""
    direct = await session.execute(
        select(Conversation, User.full_name, Space, ConversationShare)
        .join(ConversationShare, ConversationShare.conversation_id == Conversation.id)
        .join(User, User.id == Conversation.user_id)
        .join(Space, Space.id == Conversation.space_id)
        .where(ConversationShare.user_id == user.id)
    )
    found: dict[uuid.UUID, Inbox] = {}
    for conversation, owner, space, share in direct.all():
        found[conversation.id] = Inbox(
            conversation,
            owner,
            "General chat" if space.is_personal else space.name,
            space.is_personal,
            share.created_at,
            share.seen_at is None,
        )
    wide = await session.execute(
        select(Conversation, User.full_name, Space)
        .join(User, User.id == Conversation.user_id)
        .join(Space, Space.id == Conversation.space_id)
        .join(SpaceMember, SpaceMember.space_id == Space.id)
        .where(
            SpaceMember.user_id == user.id,
            Conversation.shared.is_(True),
            Conversation.user_id != user.id,
            ~select(SpaceAccessRule.space_id).where(SpaceAccessRule.space_id == Space.id).exists(),
        )
    )
    for conversation, owner, space in wide.all():
        found.setdefault(
            conversation.id,
            Inbox(conversation, owner, space.name, False, conversation.updated_at, False),
        )
    ordered = sorted(found.values(), key=lambda i: i.conversation.updated_at, reverse=True)
    return ordered[:limit]


async def unread_count(session: AsyncSession, user: User) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ConversationShare)
            .where(ConversationShare.user_id == user.id, ConversationShare.seen_at.is_(None))
        )
        or 0
    )


async def messages(session: AsyncSession, conversation: Conversation) -> list[Message]:
    return list(
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.seq)
        )
    )


# ── Documents ────────────────────────────────────────────────────────────────


async def can_read_document(session: AsyncSession, user: User, document: Document) -> bool:
    """A document of a space: anyone in the space. A document added in a chat: that chat's owner,
    and the people it is shared with (so they can open what it cites)."""
    if document.conversation_id is None:
        if user.role == Role.ADMIN:
            return True
        if await session.get(SpaceMember, (document.space_id, user.id)) is not None:
            return True
        # Not in the space, but a chat shared with you cites it: you may open what it cites.
        cited = await session.scalar(
            select(Message.id)
            .join(ConversationShare, ConversationShare.conversation_id == Message.conversation_id)
            .where(
                ConversationShare.user_id == user.id,
                Message.citations.contains([{"document_id": str(document.id)}]),
            )
            .limit(1)
        )
        return cited is not None
    conversation = await session.get(Conversation, document.conversation_id)
    return conversation is not None and await can_read(session, user, conversation)
