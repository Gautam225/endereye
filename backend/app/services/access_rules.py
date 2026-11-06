"""What each person may read from a space's tables: hidden columns, masked columns, row filters.

A rule is stored once and applied where data is read, so it can't be talked around: the DuckDB
views of a file space are built without the hidden columns and with only the rows a person may
see, and the PostgreSQL guard puts the same restriction in front of every table it rewrites. The
assistant, the SQL tab, previews and examples all read through those two places.

Who a rule applies to: one named person (whatever their role), or an audience: the space's
viewers, its members (viewers and editors, not admins), or everyone. A person nobody is known for
(a background check) gets every audience rule, never an exemption.
"""

import uuid
from dataclasses import dataclass

import sqlglot
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    Audience,
    Conversation,
    Role,
    RuleKind,
    SourceType,
    SpaceAccessRule,
    SpaceMember,
    SpaceTable,
    User,
)

MAX_RULES = 200


class InvalidRuleError(AppError):
    status_code = 400
    code = "invalid_rule"


# A row filter is a plain condition on the table's own columns. Anything that could reach other
# data or run code (sub-queries, other tables, window or aggregate functions, anything not listed)
# is refused when the rule is written, so what is applied later is known to be harmless.
_ALLOWED = (
    exp.Column, exp.Identifier, exp.Literal, exp.Null, exp.Boolean, exp.Paren,
    exp.And, exp.Or, exp.Not, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
    exp.In, exp.Between, exp.Is, exp.Like, exp.ILike, exp.Neg,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Lower, exp.Upper, exp.Coalesce,
    exp.Cast, exp.DataType, exp.Tuple,
)  # fmt: skip
_DIALECTS = {SourceType.EXTERNAL.value: "postgres"}


@dataclass(frozen=True, slots=True)
class Restriction:
    """What one person may not read from one table."""

    hidden: frozenset[str] = frozenset()
    masked: frozenset[str] = frozenset()
    row_filters: tuple[str, ...] = ()

    @property
    def row_filter(self) -> str | None:
        """The conditions together: a row must pass every one."""
        return " AND ".join(f"({f})" for f in self.row_filters) or None

    @property
    def unseen(self) -> frozenset[str]:
        """Columns the assistant must not be told about (hidden, and masked ones that are empty)."""
        return self.hidden | self.masked


Restrictions = dict[str, Restriction]  # by the table's name in SQL


async def role_of(session: AsyncSession, space_id: uuid.UUID, user: User | None) -> str:
    """admin, editor or viewer. Nobody known counts as a viewer: the strictest."""
    if user is None:
        return "viewer"
    if user.role == Role.ADMIN:
        return "admin"
    member = await session.get(SpaceMember, (space_id, user.id))
    return member.role if member else "viewer"


def applies(rule: SpaceAccessRule, role: str, user: User | None) -> bool:
    if rule.user_id is not None:
        return user is not None and rule.user_id == user.id
    if rule.audience == Audience.EVERYONE.value:
        return True
    if rule.audience == Audience.MEMBERS.value:
        return role in {"editor", "viewer"}
    return role == "viewer"


async def restrictions_for(
    session: AsyncSession, space_id: uuid.UUID, user: User | None
) -> Restrictions:
    """Every restriction that applies to this person in this space, by table name."""
    role = await role_of(session, space_id, user)
    rows = (
        await session.execute(
            select(SpaceAccessRule, SpaceTable.name)
            .join(SpaceTable, SpaceTable.id == SpaceAccessRule.table_id)
            .where(SpaceAccessRule.space_id == space_id)
            .order_by(SpaceAccessRule.created_at)
        )
    ).all()
    found: dict[str, dict[str, list[str]]] = {}
    for rule, table in rows:
        if not applies(rule, role, user):
            continue
        parts = found.setdefault(table, {"hide": [], "mask": [], "filter": []})
        if rule.kind == RuleKind.HIDE_COLUMN.value and rule.column:
            parts["hide"].append(rule.column)
        elif rule.kind == RuleKind.MASK_COLUMN.value and rule.column:
            parts["mask"].append(rule.column)
        elif rule.kind == RuleKind.ROW_FILTER.value and rule.expression:
            parts["filter"].append(rule.expression)
    return {
        table: Restriction(
            frozenset(parts["hide"]),
            frozenset(parts["mask"]) - frozenset(parts["hide"]),
            tuple(parts["filter"]),
        )
        for table, parts in found.items()
    }


# ── Writing rules ────────────────────────────────────────────────────────────


def _check_filter(text: str, table: SpaceTable) -> str:
    """The condition, normalised, or a plain reason it can't be used."""
    dialect = _DIALECTS.get(table.source_type, "duckdb")
    try:
        tree = sqlglot.parse_one(text, read=dialect)
    except SqlglotError:
        raise InvalidRuleError(
            "That condition could not be read. Write it like a WHERE clause, for example "
            "region = 'West'."
        ) from None
    if isinstance(tree, exp.Query) or tree is None:
        raise InvalidRuleError("Write a condition (a WHERE clause), not a query.")
    names = {c["name"].lower() for c in table.columns}
    for node in tree.walk():
        if not isinstance(node, _ALLOWED):
            raise InvalidRuleError(
                "A row filter can only compare this table's columns with values, using "
                "AND, OR, NOT, =, <>, <, >, IN, BETWEEN, LIKE and IS NULL."
            )
        if isinstance(node, exp.Column):
            if node.table and node.table.lower() != table.name.lower():
                raise InvalidRuleError("A row filter can only use this table's own columns.")
            if node.name.lower() not in names:
                raise InvalidRuleError(f"The table has no column called '{node.name}'.")
    return tree.sql(dialect=dialect)


async def add_rule(
    session: AsyncSession,
    space_id: uuid.UUID,
    settings: Settings,
    *,
    table_id: uuid.UUID,
    kind: str,
    column: str | None,
    expression: str | None,
    audience: str,
    user_id: uuid.UUID | None,
    created_by: uuid.UUID,
) -> SpaceAccessRule:
    table = await session.get(SpaceTable, table_id)
    if table is None or table.space_id != space_id:
        raise NotFoundError("That table is not in this space.")
    if user_id is not None and await session.get(User, user_id) is None:
        raise NotFoundError("That person does not exist.")
    count = len(
        (
            await session.scalars(
                select(SpaceAccessRule.id).where(SpaceAccessRule.space_id == space_id)
            )
        ).all()
    )
    if count >= MAX_RULES:
        raise ConflictError(f"A space can have at most {MAX_RULES} access rules.")

    text = None
    if kind == RuleKind.ROW_FILTER.value:
        if not (expression or "").strip():
            raise InvalidRuleError("Write the condition the rows must meet.")
        column = None
        text = _check_filter(expression.strip(), table)
        await _dry_run(session, space_id, settings, table, text)
    else:
        match = next((c["name"] for c in table.columns if c["name"] == column), None)
        if match is None:
            raise InvalidRuleError(f"The table has no column called '{column}'.")
        column = match

    rule = SpaceAccessRule(
        space_id=space_id,
        table_id=table_id,
        kind=kind,
        column=column,
        expression=text,
        audience=audience,
        user_id=user_id,
        created_by=created_by,
    )
    session.add(rule)
    # A shared chat holds results read under its owner's permissions; with a rule in place it
    # could show another member what they may not see, so every share in the space ends here.
    await session.execute(
        update(Conversation).where(Conversation.space_id == space_id).values(shared=False)
    )
    await session.commit()
    return rule


async def _dry_run(
    session: AsyncSession, space_id: uuid.UUID, settings: Settings, table: SpaceTable, text: str
) -> None:
    """The condition must also run (a text column compared with a number would not)."""
    from app.engine.duckdb_engine import QueryFailedError
    from app.engine.sql_guard import SqlNotAllowedError
    from app.services import engines  # engines uses this module

    engine = await engines.for_space(session, space_id, settings, unrestricted=True)
    sql = f"SELECT 1 FROM {table.name} WHERE ({text}) LIMIT 1"
    try:
        await engine.run(
            session,
            engine.check(sql),
            max_rows=1,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except (SqlNotAllowedError, QueryFailedError) as exc:
        raise InvalidRuleError(
            f"That condition does not run on this table: {exc.message}"
        ) from None


async def delete_rule(session: AsyncSession, space_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    rule = await session.get(SpaceAccessRule, rule_id)
    if rule is None or rule.space_id != space_id:
        raise NotFoundError("That rule does not exist.")
    await session.delete(rule)
    await session.commit()


async def list_rules(
    session: AsyncSession, space_id: uuid.UUID
) -> list[tuple[SpaceAccessRule, str, str | None]]:
    """Each rule with its table's name and the named person's email, for the admin screen."""
    rows = await session.execute(
        select(SpaceAccessRule, SpaceTable.name, User.email)
        .join(SpaceTable, SpaceTable.id == SpaceAccessRule.table_id)
        .outerjoin(User, User.id == SpaceAccessRule.user_id)
        .where(SpaceAccessRule.space_id == space_id)
        .order_by(SpaceAccessRule.created_at)
    )
    return [(rule, table, email) for rule, table, email in rows.all()]
