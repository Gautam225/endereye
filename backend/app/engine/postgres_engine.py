"""Running a checked query on an external PostgreSQL database.

Only called with SQL that has passed pg_sql_guard, on a session opened by
`connections.verified_session` (read-only transaction, login re-checked as read-only). On top of
that, each query gets its own statement timeout, its rows are read through a cursor and stopped
at the row limit, and long cell values are cut, so one query can't hold the server or this
process for long or fill its memory.

Errors are mapped to a few messages. A problem with the query itself (a column that doesn't
exist, a type mismatch) keeps the database's own short message, because the assistant needs it
to correct the query. Anything about the server, the login or the network gets a fixed message.
"""

import asyncio
import logging
import time
from typing import Any

import asyncpg

from app.core.errors import AppError
from app.engine.duckdb_engine import (
    CancelToken,
    Column,
    QueryCancelledError,
    QueryFailedError,
    QueryResult,
    QueryTimeoutError,
    to_json_value,
)

logger = logging.getLogger(__name__)

MAX_CELL_CHARS = 10_000
MAX_MESSAGE_CHARS = 200
TYPE_NAMES = {
    "int2": "SMALLINT",
    "int4": "INTEGER",
    "int8": "BIGINT",
    "numeric": "DECIMAL",
    "float4": "FLOAT",
    "float8": "DOUBLE",
    "text": "VARCHAR",
    "varchar": "VARCHAR",
    "bpchar": "VARCHAR",
    "name": "VARCHAR",
    "bool": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "timestamptz": "TIMESTAMP WITH TIME ZONE",
    "time": "TIME",
    "timetz": "TIME",
    "interval": "INTERVAL",
    "uuid": "UUID",
    "json": "JSON",
    "jsonb": "JSON",
    "bytea": "BLOB",
}


class DatabaseUnavailableError(AppError):
    status_code = 502
    code = "database_unavailable"


def type_name(attribute: asyncpg.Attribute) -> str:
    name = attribute.type.name
    if name.endswith("[]"):
        return f"{TYPE_NAMES.get(name[:-2], name[:-2].upper())}[]"
    return TYPE_NAMES.get(name, name.upper())


def _cell(value: Any) -> Any:
    value = to_json_value(value)
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


def failure(exc: BaseException, cancel: CancelToken | None, timeout_seconds: float) -> AppError:
    """The error to show for a failed query."""
    if cancel is not None and cancel.cancelled:
        return QueryCancelledError("Stopped.")
    if isinstance(exc, asyncpg.QueryCanceledError):
        return QueryTimeoutError(
            f"The query took longer than {timeout_seconds:g} seconds and was stopped. "
            "Try a narrower question."
        )
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return QueryTimeoutError(f"The query took longer than {timeout_seconds:g} seconds.")
    if isinstance(exc, asyncpg.InsufficientPrivilegeError):
        return QueryFailedError(
            "The database login is not allowed to read something this query uses."
        )
    if isinstance(exc, asyncpg.ReadOnlySQLTransactionError):
        return QueryFailedError("The database refused to change anything: access is read-only.")
    if isinstance(exc, asyncpg.PostgresError):
        code = exc.sqlstate or ""
        if code.startswith(("42", "22")):  # a problem in the query itself
            message = " ".join(str(getattr(exc, "message", None) or exc).split())[
                :MAX_MESSAGE_CHARS
            ]
            return QueryFailedError(f"The database could not run the query: {message}")
        if code.startswith("40"):
            return QueryFailedError("The database stopped the query (a conflict). Try again.")
        return QueryFailedError(f"The database could not run this query (code {code or '?'}).")
    if isinstance(exc, asyncpg.InterfaceError | asyncpg.ConnectionDoesNotExistError | OSError):
        return DatabaseUnavailableError("The connection to the database was lost. Try again.")
    return QueryFailedError("The query failed for an unknown reason.")


async def run_query(
    conn: asyncpg.Connection,
    sql: str,
    *,
    max_rows: int,
    timeout_seconds: float,
    cancel: CancelToken | None = None,
) -> QueryResult:
    """Run one checked SELECT inside the session's read-only transaction."""
    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    if cancel is not None:
        cancel.attach(lambda: loop.call_soon_threadsafe(conn.terminate))
    try:
        await conn.execute(f"SET LOCAL statement_timeout = {max(1, int(timeout_seconds * 1000))}")
        statement = await conn.prepare(sql, timeout=timeout_seconds)
        columns = [Column(a.name, type_name(a)) for a in statement.get_attributes()]
        cursor = await statement.cursor()
        records = await cursor.fetch(max_rows + 1, timeout=timeout_seconds + 5)
    except Exception as exc:
        raise failure(exc, cancel, timeout_seconds) from None
    finally:
        if cancel is not None:
            cancel.detach()

    truncated = len(records) > max_rows
    rows = [[_cell(v) for v in record.values()] for record in records[:max_rows]]
    return QueryResult(
        columns=columns,
        rows=rows,
        truncated=truncated,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
