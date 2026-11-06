import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

KindName = Literal["hide_column", "mask_column", "row_filter"]
AudienceName = Literal["viewers", "members", "everyone"]


class AccessRuleCreate(BaseModel):
    table_id: uuid.UUID
    kind: KindName
    column: str | None = Field(default=None, max_length=255)  # hide and mask
    expression: str | None = Field(default=None, max_length=500)  # row filter: a condition
    audience: AudienceName = "viewers"
    user_id: uuid.UUID | None = None  # one person's rule: the audience is then ignored


class AccessRuleOut(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    table: str
    kind: KindName
    column: str | None
    expression: str | None
    audience: AudienceName
    user_id: uuid.UUID | None
    user_email: str | None
    created_at: datetime
