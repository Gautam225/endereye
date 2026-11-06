import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.chat import ConversationDetail, ConversationOut


class SharePerson(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    seen_at: datetime | None = None  # when they first opened it


class SharesOut(BaseModel):
    people: list[SharePerson]
    everyone: bool  # also shared with every member of the space (the older kind of sharing)


class SharesIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(max_length=50)


class InboxItem(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    title: str
    owner_name: str
    space_name: str
    personal: bool
    shared_at: datetime
    updated_at: datetime
    unread: bool


class SharedChat(ConversationDetail):
    space_id: uuid.UUID
    space_name: str
    personal: bool


class BranchOut(ConversationOut):
    space_id: uuid.UUID  # where the copy lives (your General chat)


class UnreadOut(BaseModel):
    count: int
