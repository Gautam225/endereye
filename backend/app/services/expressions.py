"""SQL expressions: business definitions (measures, filters, dimensions) written as SQL.

Unlike text instructions the AI has to interpret, an expression is applied exactly as written.
Every expression is tested before it is saved: it is run against its table, through the same
SQL guard and read-only engine as any query, so a broken or unsafe definition can't be stored.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    ExpressionTest,
    ExpressionVersion,
    Role,
    SpaceMember,
    SpaceTable,
    SqlExpression,
    User,
)
from app.engine.duckdb_engine import quote_identifier
from app.schemas.knowledge import (
    ExpressionCreate,
    ExpressionOut,
    ExpressionTestCreate,
    ExpressionTestOut,
    ExpressionTestUpdate,
    ExpressionUpdate,
    ExpressionVersionOut,
    TestRunOut,
)
from app.services import engines, indexing, spaces
from app.services.spaces import SpaceAccess


async def list_expressions(session: AsyncSession, space_id: uuid.UUID) -> list[SqlExpression]:
    return list(
        await session.scalars(
            select(SqlExpression)
            .where(SqlExpression.space_id == space_id)
            .order_by(SqlExpression.type, SqlExpression.name)
        )
    )


def probe_sql(kind: str, expression: str, table: str) -> str:
    """A query that uses the expression the way it will be used."""
    name = quote_identifier(table)
    if kind == "measure":
        return f"SELECT {expression} AS value FROM {name}"
    if kind == "filter":
        return f"SELECT count(*) AS matching_rows FROM {name} WHERE {expression}"
    return f"SELECT {expression} AS value FROM {name} LIMIT 5"


async def check_expression(
    session: AsyncSession,
    access: SpaceAccess,
    kind: str,
    expression: str,
    table_name: str | None,
    settings: Settings,
) -> str:
    """Raise a readable error unless the expression runs. Returns it, tidied."""
    expression = expression.strip().rstrip(";").strip()
    names = set(
        await session.scalars(select(SpaceTable.name).where(SpaceTable.space_id == access.space.id))
    )
    if table_name is None:
        # Without a table there is nothing to run it on; it is only checked for safety.
        if not names:
            return expression
        probe = f"SELECT {expression}"
        try:
            (await engines.for_space(session, access.space.id, settings)).check(probe)
        except AppError as exc:
            raise AppError(
                f"This expression can't be used: {exc.message}", code="invalid_expression"
            ) from None
        return expression
    if table_name not in names:
        raise AppError(
            f"There is no table called '{table_name}' in this space.", code="invalid_expression"
        )
    try:
        await spaces.run_sql(session, access, probe_sql(kind, expression, table_name), settings)
    except AppError as exc:
        raise AppError(
            f"This expression doesn't work on {table_name}: {exc.message}",
            code="invalid_expression",
        ) from None
    return expression


async def _get(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID
) -> SqlExpression:
    found = await session.get(SqlExpression, expression_id)
    if found is None or found.space_id != access.space.id:
        raise NotFoundError("That expression does not exist in this space.")
    return found


async def get_expression(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID
) -> SqlExpression:
    return await _get(session, access, expression_id)


async def _save(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(
            f"This space already has a definition called '{name}'.", code="expression_name_taken"
        ) from None


# ── Reading (the shared layer: everyone in the space can see it) ─────────────


async def list_out(session: AsyncSession, space_id: uuid.UUID) -> list[ExpressionOut]:
    """Every definition with its owner, version and how its tests stand."""
    items = await list_expressions(session, space_id)
    owners = {
        u.id: u.full_name
        for u in await session.scalars(
            select(User).where(User.id.in_({i.owner_id for i in items if i.owner_id}))
        )
    }
    totals: dict[uuid.UUID, tuple[int, int]] = {}
    for expression_id, total, failing in await session.execute(
        select(
            ExpressionTest.expression_id,
            func.count(),
            func.count().filter(ExpressionTest.last_status.in_(("fail", "error"))),
        )
        .join(SqlExpression, SqlExpression.id == ExpressionTest.expression_id)
        .where(SqlExpression.space_id == space_id)
        .group_by(ExpressionTest.expression_id)
    ):
        totals[expression_id] = (total, failing)
    out = []
    for item in items:
        total, failing = totals.get(item.id, (0, 0))
        out.append(
            ExpressionOut.model_validate(item).model_copy(
                update={
                    "owner_name": owners.get(item.owner_id) if item.owner_id else None,
                    "tests_total": total,
                    "tests_failing": failing,
                }
            )
        )
    return out


async def one_out(session: AsyncSession, item: SqlExpression) -> ExpressionOut:
    return next(e for e in await list_out(session, item.space_id) if e.id == item.id)


async def list_versions(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID
) -> list[ExpressionVersionOut]:
    await _get(session, access, expression_id)
    rows = await session.execute(
        select(ExpressionVersion, User.full_name)
        .outerjoin(User, User.id == ExpressionVersion.changed_by)
        .where(ExpressionVersion.expression_id == expression_id)
        .order_by(ExpressionVersion.version.desc())
    )
    return [
        ExpressionVersionOut.model_validate(v).model_copy(update={"changed_by_name": name})
        for v, name in rows
    ]


# ── Tests: does the definition still give the right number? ──────────────────


def metric_sql(kind: str, expression: str, table: str, where: str | None) -> str:
    """The number a test looks at: a measure's value, how many rows a filter keeps, or how many
    different values a dimension has, over the table (narrowed by the test's condition)."""
    name = quote_identifier(table)
    condition = f" WHERE ({where})" if where else ""
    if kind == "measure":
        return f"SELECT {expression} AS value FROM {name}{condition}"
    if kind == "filter":
        extra = f" AND ({where})" if where else ""
        return f"SELECT count(*) AS value FROM {name} WHERE ({expression}){extra}"
    return f"SELECT count(DISTINCT {expression}) AS value FROM {name}{condition}"


@dataclass(frozen=True, slots=True)
class Outcome:
    status: str  # pass, fail or error
    value: float | None
    detail: str


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("it did not give a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError("it did not give a number") from None


async def evaluate(
    session: AsyncSession,
    access: SpaceAccess,
    kind: str,
    expression: str,
    table_name: str,
    where: str | None,
    settings: Settings,
) -> float:
    """The number the definition gives right now, as the person asking may read the data."""
    result = await spaces.run_sql(
        session, access, metric_sql(kind, expression, table_name, where), settings
    )
    if not result.rows or not result.rows[0]:
        raise AppError("It returned no value.", code="invalid_expression")
    try:
        return _number(result.rows[0][0])
    except ValueError as exc:
        raise AppError(f"The result is not a number: {exc}.", code="invalid_expression") from None


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= tolerance


async def _outcome(
    session: AsyncSession,
    access: SpaceAccess,
    test: ExpressionTest,
    kind: str,
    expression: str,
    table_name: str | None,
    settings: Settings,
) -> Outcome:
    if table_name is None:
        return Outcome("error", None, "The definition has no table, so it can't be tested.")
    try:
        actual = await evaluate(
            session, access, kind, expression, table_name, test.where_sql, settings
        )
    except AppError as exc:
        return Outcome("error", None, exc.message[:300])
    if _close(actual, test.expected, test.tolerance):
        return Outcome("pass", actual, "")
    return Outcome("fail", actual, f"Got {actual:g}, expected {test.expected:g}.")


def _record(test: ExpressionTest, outcome: Outcome, version: int) -> None:
    test.last_status = outcome.status
    test.last_value = outcome.value
    test.last_detail = outcome.detail
    test.last_checked_at = datetime.now(UTC)
    test.last_version = version


async def _tests_of(session: AsyncSession, expression_id: uuid.UUID) -> list[ExpressionTest]:
    return list(
        await session.scalars(
            select(ExpressionTest)
            .where(ExpressionTest.expression_id == expression_id)
            .order_by(ExpressionTest.created_at, ExpressionTest.id)
        )
    )


def _run_out(tests: list[ExpressionTest]) -> TestRunOut:
    passed = sum(t.last_status == "pass" for t in tests)
    return TestRunOut(
        passed=passed,
        failed=len(tests) - passed,
        tests=[ExpressionTestOut.model_validate(t) for t in tests],
    )


async def list_tests(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID
) -> list[ExpressionTestOut]:
    await _get(session, access, expression_id)
    return [ExpressionTestOut.model_validate(t) for t in await _tests_of(session, expression_id)]


MAX_TESTS_PER_EXPRESSION = 20


async def create_test(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    expression_id: uuid.UUID,
    data: ExpressionTestCreate,
    settings: Settings,
) -> ExpressionTest:
    item = await _get(session, access, expression_id)
    if item.table_name is None:
        raise AppError(
            "A test needs the definition to be written for a table.", code="validation_error"
        )
    if len(await _tests_of(session, item.id)) >= MAX_TESTS_PER_EXPRESSION:
        raise AppError(
            f"A definition can have at most {MAX_TESTS_PER_EXPRESSION} tests.",
            code="too_many_tests",
        )
    test = ExpressionTest(
        expression_id=item.id,
        name=data.name,
        where_sql=data.where_sql or None,
        expected=data.expected,
        tolerance=data.tolerance,
        created_by=user.id,
    )
    outcome = await _outcome(
        session, access, test, item.type, item.expression, item.table_name, settings
    )
    if outcome.status == "error":  # the condition itself is broken: don't keep it
        raise AppError(f"This test can't run: {outcome.detail}", code="invalid_expression")
    _record(test, outcome, item.version)
    session.add(test)
    await session.commit()
    return test


async def _get_test(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID, test_id: uuid.UUID
) -> ExpressionTest:
    await _get(session, access, expression_id)
    test = await session.get(ExpressionTest, test_id)
    if test is None or test.expression_id != expression_id:
        raise NotFoundError("That test does not exist.")
    return test


async def update_test(
    session: AsyncSession,
    access: SpaceAccess,
    expression_id: uuid.UUID,
    test_id: uuid.UUID,
    data: ExpressionTestUpdate,
    settings: Settings,
) -> ExpressionTest:
    item = await _get(session, access, expression_id)
    test = await _get_test(session, access, expression_id, test_id)
    changes = data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "where_sql":
            value = value or None
        if value is not None or key == "where_sql":
            setattr(test, key, value)
    _record(
        test,
        await _outcome(
            session, access, test, item.type, item.expression, item.table_name, settings
        ),
        item.version,
    )
    await session.commit()
    return test


async def delete_test(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID, test_id: uuid.UUID
) -> None:
    await session.delete(await _get_test(session, access, expression_id, test_id))
    await session.commit()


async def run_tests(
    session: AsyncSession,
    access: SpaceAccess,
    expression_id: uuid.UUID,
    settings: Settings,
) -> TestRunOut:
    item = await _get(session, access, expression_id)
    tests = await _tests_of(session, item.id)
    for test in tests:
        _record(
            test,
            await _outcome(
                session, access, test, item.type, item.expression, item.table_name, settings
            ),
            item.version,
        )
    await session.commit()
    return _run_out(tests)


async def run_all_tests(
    session: AsyncSession, access: SpaceAccess, settings: Settings
) -> TestRunOut:
    """Every test of every definition in the space: the health of the whole metric layer."""
    everything: list[ExpressionTest] = []
    for item in await list_expressions(session, access.space.id):
        tests = await _tests_of(session, item.id)
        for test in tests:
            _record(
                test,
                await _outcome(
                    session, access, test, item.type, item.expression, item.table_name, settings
                ),
                item.version,
            )
        everything.extend(tests)
    await session.commit()
    return _run_out(everything)


# ── Changing a definition ────────────────────────────────────────────────────

DEFINITION_FIELDS = (
    "name",
    "type",
    "expression",
    "table_name",
    "description",
    "synonyms",
    "is_default",
)


def _snapshot(item: SqlExpression, user: User | None, note: str) -> ExpressionVersion:
    return ExpressionVersion(
        expression_id=item.id,
        version=item.version,
        name=item.name,
        type=item.type,
        expression=item.expression,
        table_name=item.table_name,
        description=item.description,
        synonyms=list(item.synonyms),
        is_default=item.is_default,
        note=note[:300],
        changed_by=user.id if user else None,
    )


async def _check_owner(session: AsyncSession, access: SpaceAccess, owner_id: uuid.UUID) -> None:
    owner = await session.get(User, owner_id)
    allowed = owner is not None and owner.is_active
    if allowed and owner.role != Role.ADMIN:
        allowed = await session.get(SpaceMember, (access.space.id, owner_id)) is not None
    if not allowed:
        raise AppError("The owner must be someone who can use this space.", code="validation_error")


async def create_expression(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: ExpressionCreate,
    settings: Settings,
) -> SqlExpression:
    expression = await check_expression(
        session, access, data.type, data.expression, data.table_name, settings
    )
    item = SqlExpression(
        space_id=access.space.id,
        name=data.name,
        type=data.type,
        expression=expression,
        table_name=data.table_name,
        description=data.description,
        synonyms=data.synonyms,
        is_default=data.is_default,
        created_by=user.id,
        owner_id=user.id,
        version=1,
    )
    session.add(item)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(
            f"This space already has a definition called '{data.name}'.",
            code="expression_name_taken",
        ) from None
    session.add(_snapshot(item, user, "Created"))
    await _save(session, data.name)
    await indexing.items_changed(session, access.space.id, settings)
    return item


async def _failing_with(
    session: AsyncSession,
    access: SpaceAccess,
    item: SqlExpression,
    kind: str,
    expression: str,
    table_name: str | None,
    settings: Settings,
) -> tuple[list[tuple[ExpressionTest, Outcome]], list[str]]:
    """Run the definition's tests against a change that has not been saved yet."""
    results = [
        (test, await _outcome(session, access, test, kind, expression, table_name, settings))
        for test in await _tests_of(session, item.id)
    ]
    problems = [
        f"'{test.name}': {outcome.detail}" for test, outcome in results if outcome.status != "pass"
    ]
    return results, problems


async def _apply(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    item: SqlExpression,
    changes: dict[str, Any],
    *,
    note: str,
    accept_failing_tests: bool,
    settings: Settings,
) -> SqlExpression:
    kind = changes.get("type", item.type)
    table_name = changes.get("table_name", item.table_name)
    expression = changes.get("expression", item.expression)
    is_default = changes.get("is_default", item.is_default)
    if is_default and kind != "filter":
        raise AppError("Only a filter can be applied by default.", code="validation_error")
    if "owner_id" in changes and changes["owner_id"] is not None:
        await _check_owner(session, access, changes["owner_id"])
    computed = {"type", "table_name", "expression"} & {
        k for k in changes if changes[k] != getattr(item, k)
    }
    if computed:
        expression = await check_expression(session, access, kind, expression, table_name, settings)
    wanted = {field: changes.get(field, getattr(item, field)) for field in DEFINITION_FIELDS}
    wanted["expression"] = expression  # as tidied by the check
    changed = [field for field in DEFINITION_FIELDS if wanted[field] != getattr(item, field)]

    results: list[tuple[ExpressionTest, Outcome]] = []
    if computed:
        results, problems = await _failing_with(
            session, access, item, kind, expression, table_name, settings
        )
        if problems and not accept_failing_tests:
            raise ConflictError(
                f"This change makes {len(problems)} of this definition's tests fail: "
                + "; ".join(problems)[:600],
                code="tests_failed",
                details={"failing": problems},
            )

    item.type, item.table_name, item.expression, item.is_default = (
        kind,
        table_name,
        expression,
        is_default,
    )
    for field in ("name", "description", "synonyms"):
        if field in changes:
            setattr(item, field, changes[field])
    if changes.get("owner_id") is not None:
        item.owner_id = changes["owner_id"]
    if changed:
        item.version += 1
        session.add(_snapshot(item, user, note))
        for test, outcome in results:
            _record(test, outcome, item.version)
    await _save(session, item.name)
    if changed:
        await indexing.items_changed(session, access.space.id, settings)
    return item


async def update_expression(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    expression_id: uuid.UUID,
    data: ExpressionUpdate,
    settings: Settings,
) -> SqlExpression:
    item = await _get(session, access, expression_id)
    changes = data.model_dump(exclude_unset=True, exclude={"note", "accept_failing_tests"})
    return await _apply(
        session,
        access,
        user,
        item,
        changes,
        note=data.note or "",
        accept_failing_tests=data.accept_failing_tests,
        settings=settings,
    )


async def restore_version(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    expression_id: uuid.UUID,
    version: int,
    accept_failing_tests: bool,
    settings: Settings,
) -> SqlExpression:
    """Go back to an earlier definition. It becomes a new version, so nothing is lost."""
    item = await _get(session, access, expression_id)
    old = await session.scalar(
        select(ExpressionVersion).where(
            ExpressionVersion.expression_id == item.id, ExpressionVersion.version == version
        )
    )
    if old is None:
        raise NotFoundError("That version does not exist.")
    changes = {field: getattr(old, field) for field in DEFINITION_FIELDS}
    return await _apply(
        session,
        access,
        user,
        item,
        changes,
        note=f"Restored version {version}",
        accept_failing_tests=accept_failing_tests,
        settings=settings,
    )


async def delete_expression(
    session: AsyncSession, access: SpaceAccess, expression_id: uuid.UUID, settings: Settings
) -> None:
    await session.delete(await _get(session, access, expression_id))
    await session.commit()
    await indexing.items_changed(session, access.space.id, settings)
