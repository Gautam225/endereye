"""What each person may read from a space's tables. Administrators only: an editor could
otherwise lift the rule that limits them."""

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import AdminUser, SettingsDep, require_admin
from app.db.models import SpaceAccessRule
from app.db.session import SessionDep
from app.schemas.access import AccessRuleCreate, AccessRuleOut
from app.services import access_rules as service

router = APIRouter(
    prefix="/spaces/{space_id}/access-rules",
    tags=["access"],
    dependencies=[Depends(require_admin)],
)


def _out(rule: SpaceAccessRule, table: str, email: str | None) -> AccessRuleOut:
    return AccessRuleOut(
        id=rule.id,
        table_id=rule.table_id,
        table=table,
        kind=rule.kind,  # type: ignore[arg-type]
        column=rule.column,
        expression=rule.expression,
        audience=rule.audience,  # type: ignore[arg-type]
        user_id=rule.user_id,
        user_email=email,
        created_at=rule.created_at,
    )


@router.get("", response_model=list[AccessRuleOut])
async def list_rules(space_id: uuid.UUID, session: SessionDep) -> list[AccessRuleOut]:
    return [_out(*row) for row in await service.list_rules(session, space_id)]


@router.post("", response_model=AccessRuleOut, status_code=status.HTTP_201_CREATED)
async def add_rule(
    space_id: uuid.UUID,
    body: AccessRuleCreate,
    admin: AdminUser,
    session: SessionDep,
    settings: SettingsDep,
) -> AccessRuleOut:
    rule = await service.add_rule(
        session,
        space_id,
        settings,
        table_id=body.table_id,
        kind=body.kind,
        column=body.column,
        expression=body.expression,
        audience=body.audience,
        user_id=body.user_id,
        created_by=admin.id,
    )
    rows = await service.list_rules(session, space_id)
    return next(_out(*row) for row in rows if row[0].id == rule.id)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(space_id: uuid.UUID, rule_id: uuid.UUID, session: SessionDep) -> Response:
    await service.delete_rule(session, space_id, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
