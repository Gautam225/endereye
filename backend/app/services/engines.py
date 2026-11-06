"""One way to check and run a space's SQL, whatever the data lives in.

A space's tables are files (DuckDB, on this machine) or tables of one external PostgreSQL
database. Every route that runs SQL (the assistant, an edited query, a table preview, a saved
example, a definition) goes through `for_space(...)`, so each of them gets the same two steps:
`check` (the SQL guard of that engine) and `run` (the engine's restricted execution). Nothing
runs SQL that skipped `check`.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError
from app.db.models import DbConnection, SourceType, SpaceColumn, SpaceTable, User
from app.engine import duckdb_engine, pg_sql_guard, postgres_engine
from app.engine.duckdb_engine import CancelToken, QueryResult
from app.engine.sql_guard import check_query
from app.services import access_rules, connections, spaces
from app.services.access_rules import Restrictions


@dataclass(frozen=True, slots=True)
class CheckedQuery:
    display: str  # what is shown and saved: the query as written, with the space's table names
    run: str  # what is executed (for PostgreSQL: real, quoted names and a row cap)


class SpaceEngine(Protocol):
    dialect: str
    # Whether result rows may be sent to the AI service to write the explanation.
    shares_results: bool
    # What the person asking may not read, by table name (already applied by `run`).
    restrictions: Restrictions

    def check(self, sql: str, only_tables: set[str] | None = None) -> CheckedQuery:
        """Raises SqlNotAllowedError unless the SQL may run. `only_tables` narrows the tables
        that may be used (the assistant gets the ones it was shown)."""

    async def run(
        self,
        session: AsyncSession,
        checked: CheckedQuery,
        *,
        max_rows: int,
        timeout_seconds: float,
        cancel: CancelToken | None = None,
    ) -> QueryResult: ...


class FileEngine:
    """Tables that are files or Delta folders, queried with DuckDB on this machine."""

    dialect = "duckdb"
    shares_results = True

    def __init__(self, tables: list[SpaceTable], restrictions: Restrictions | None = None) -> None:
        self._tables = tables
        self.restrictions = restrictions or {}

    def check(self, sql: str, only_tables: set[str] | None = None) -> CheckedQuery:
        names = {t.name for t in self._tables}
        text = check_query(sql, names if only_tables is None else only_tables)
        return CheckedQuery(text, text)

    async def run(
        self,
        session: AsyncSession,
        checked: CheckedQuery,
        *,
        max_rows: int,
        timeout_seconds: float,
        cancel: CancelToken | None = None,
    ) -> QueryResult:
        sources = [spaces.table_source(t, self.restrictions.get(t.name)) for t in self._tables]
        return await spaces.in_thread(
            lambda: duckdb_engine.run_query(
                sources,
                checked.run,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
                cancel=cancel,
            )
        )


class PostgresEngine:
    """Tables of one external PostgreSQL database, read through its read-only login."""

    dialect = "postgresql"

    def __init__(
        self,
        connection: DbConnection,
        tables: list[pg_sql_guard.AllowedTable],
        settings: Settings,
        restrictions: Restrictions | None = None,
    ) -> None:
        self.restrictions = restrictions or {}
        self._connection = connection
        self._tables = tables
        self._settings = settings
        self.shares_results = bool(connection and connection.share_results_with_ai)

    def check(self, sql: str, only_tables: set[str] | None = None) -> CheckedQuery:
        tables = self._tables
        if only_tables is not None:
            wanted = {n.lower() for n in only_tables}
            tables = [t for t in tables if t.sql_name.lower() in wanted]
        checked = pg_sql_guard.check_query(sql, tables, self._settings.query_max_rows)
        return CheckedQuery(checked.display, checked.run)

    async def run(
        self,
        session: AsyncSession,
        checked: CheckedQuery,
        *,
        max_rows: int,
        timeout_seconds: float,
        cancel: CancelToken | None = None,
    ) -> QueryResult:
        # The guard capped the rows at the configured limit; a smaller cap (a preview, an
        # example check) is applied by the cursor.
        async with connections.verified_session(session, self._connection, self._settings) as conn:
            return await postgres_engine.run_query(
                conn,
                checked.run,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
                cancel=cancel,
            )


async def for_space(
    session: AsyncSession,
    space_id: uuid.UUID,
    settings: Settings,
    user: User | None = None,
    *,
    unrestricted: bool = False,
) -> SpaceEngine:
    """The engine for a space, as one person sees it. `user=None` is the strictest view: every
    audience rule applies. Only the code that writes access rules asks for `unrestricted`."""
    tables = await spaces.list_tables(session, space_id)
    restrictions: Restrictions = (
        {} if unrestricted else await access_rules.restrictions_for(session, space_id, user)
    )
    external = [t for t in tables if t.source_type == SourceType.EXTERNAL.value]
    if not external:
        return FileEngine(tables, restrictions)
    if len(external) != len(tables) or len({t.connection_id for t in external}) != 1:
        # Never created by the app (a space uses files or one connection); refuse to guess.
        raise ConflictError(
            "This space mixes files and database tables, so its queries can't run.",
            code="space_mixed_sources",
        )
    connection = await session.get(DbConnection, external[0].connection_id)
    if connection is None:
        raise ConflictError("The connection of this space no longer exists.", code="no_connection")

    columns = await session.scalars(
        select(SpaceColumn)
        .where(SpaceColumn.table_id.in_([t.id for t in external]), SpaceColumn.hidden.is_(False))
        .order_by(SpaceColumn.table_id, SpaceColumn.position)
    )
    visible: dict[uuid.UUID, dict[str, str]] = {}
    for column in columns:
        visible.setdefault(column.table_id, {})[column.name] = column.type
    allowed = []
    for t in external:
        rule = restrictions.get(t.name)
        shown = {
            name: kind
            for name, kind in visible.get(t.id, {}).items()
            if rule is None or name not in rule.hidden
        }
        allowed.append(
            pg_sql_guard.AllowedTable(
                sql_name=t.name,
                schema=t.source_ref.split(".", 1)[0],
                table=t.source_ref.split(".", 1)[1],
                columns=shown,
                masked=tuple(n for n in shown if rule and n in rule.masked),
                row_filter=rule.row_filter if rule else None,
            )
        )
    return PostgresEngine(connection, allowed, settings, restrictions)
