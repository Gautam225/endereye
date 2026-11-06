"""DuckDB: runs a space's SQL over its Parquet files and Delta tables.

Every query gets a fresh in-memory connection that can see only that space's tables (as
views). After the views are created, file access is limited to exactly those files and
folders, and the settings are locked, so SQL can't read anything else or undo the limits.
All functions here are blocking; call them from a worker thread.
"""

import base64
import datetime as dt
import decimal
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb

from app.core.errors import AppError

logger = logging.getLogger(__name__)

Kind = Literal["upload", "delta_path"]
# Integers beyond this lose precision in JavaScript, so they are sent as text.
JS_SAFE_INTEGER = 2**53 - 1


class QueryFailedError(AppError):
    status_code = 400
    code = "query_failed"


class QueryTimeoutError(AppError):
    status_code = 400
    code = "query_timeout"


class QueryCancelledError(AppError):
    status_code = 400
    code = "query_cancelled"


class CancelToken:
    """Lets another thread stop a running query (a user pressed Stop)."""

    def __init__(self) -> None:
        self.cancelled = False
        self._interrupt: Callable[[], None] | None = None
        self._lock = threading.Lock()

    def attach(self, interrupt: Callable[[], None]) -> None:
        with self._lock:
            self._interrupt = interrupt
            if self.cancelled:
                interrupt()

    def detach(self) -> None:
        with self._lock:
            self._interrupt = None

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            if self._interrupt is not None:
                self._interrupt()


@dataclass(frozen=True, slots=True)
class TableSource:
    name: str  # the name used in SQL
    kind: Kind
    path: str  # Parquet file (upload) or Delta folder
    # What this person may read (see services/access_rules.py). The view is built so that a hidden
    # column does not exist, a masked one reads as NULL and only the matching rows are there, which
    # holds for `SELECT *` and for anything else the query does.
    hidden: tuple[str, ...] = ()
    masked: tuple[tuple[str, str], ...] = ()  # (column, type)
    row_filter: str | None = None


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: list[Column]
    rows: list[list[Any]]
    truncated: bool  # more rows existed than were returned
    elapsed_ms: int


def install_extensions() -> None:
    """Download the Delta and Excel extensions once (they are cached by DuckDB)."""
    with duckdb.connect() as con:
        for extension in ("delta", "excel"):
            try:
                con.execute(f"INSTALL {extension}")
            except duckdb.Error as exc:
                logger.warning(
                    "DuckDB extension %s is not available: %s", extension, first_line(exc)
                )


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _posix(path: str) -> str:
    return Path(path).as_posix()


def _scan(source: TableSource) -> str:
    location = quote_literal(_posix(source.path))
    return f"read_parquet({location})" if source.kind == "upload" else f"delta_scan({location})"


def _select(source: TableSource) -> str:
    """The view's query: everything in the table, less what this person may not read."""
    text = "SELECT *"
    if source.hidden:
        text += f" EXCLUDE ({', '.join(quote_identifier(name) for name in source.hidden)})"
    if source.masked:
        text += (
            " REPLACE ("
            + ", ".join(
                f"CAST(NULL AS {kind}) AS {quote_identifier(name)}" for name, kind in source.masked
            )
            + ")"
        )
    text += f" FROM {_scan(source)}"
    if source.row_filter:
        text += f" WHERE {source.row_filter}"
    return text


def open_views(sources: list[TableSource]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    try:
        if any(source.kind == "delta_path" for source in sources):
            con.execute("LOAD delta")
        for source in sources:
            con.execute(f"CREATE VIEW {quote_identifier(source.name)} AS {_select(source)}")
        files = [quote_literal(_posix(s.path)) for s in sources if s.kind == "upload"]
        folders = [quote_literal(_posix(s.path) + "/") for s in sources if s.kind == "delta_path"]
        if files:
            con.execute(f"SET allowed_paths = [{', '.join(files)}]")
        if folders:
            con.execute(f"SET allowed_directories = [{', '.join(folders)}]")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
    except BaseException:
        con.close()
        raise
    return con


def run_query(
    sources: list[TableSource],
    sql: str,
    *,
    max_rows: int,
    timeout_seconds: float,
    cancel: CancelToken | None = None,
) -> QueryResult:
    """Run SQL that has already passed the SQL guard."""
    con = open_views(sources)
    timer = threading.Timer(timeout_seconds, con.interrupt)
    started = time.perf_counter()
    timer.start()
    if cancel is not None:
        cancel.attach(con.interrupt)
    try:
        cursor = con.execute(sql)
        columns = [Column(str(d[0]), str(d[1])) for d in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
    except duckdb.InterruptException:
        if cancel is not None and cancel.cancelled:
            raise QueryCancelledError("The query was stopped.") from None
        raise QueryTimeoutError(
            f"The query took longer than {timeout_seconds:g} seconds and was stopped."
        ) from None
    except duckdb.Error as exc:
        raise QueryFailedError(f"The query failed: {first_line(exc)}") from None
    finally:
        timer.cancel()
        if cancel is not None:
            cancel.detach()
        con.close()
    return QueryResult(
        columns=columns,
        rows=[[to_json_value(value) for value in row] for row in rows[:max_rows]],
        truncated=len(rows) > max_rows,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )


def describe(source: TableSource) -> tuple[list[Column], int]:
    """Columns and row count of one table."""
    con = open_views([source])
    try:
        name = quote_identifier(source.name)
        columns = [Column(str(r[0]), str(r[1])) for r in con.execute(f"DESCRIBE {name}").fetchall()]
        row_count = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
    except duckdb.Error as exc:
        raise QueryFailedError(f"Could not read the table: {first_line(exc)}") from None
    finally:
        con.close()
    return columns, int(row_count)


FILE_READERS = {
    ".csv": "read_csv({path})",
    ".tsv": "read_csv({path}, delim = '\t')",
    ".txt": "read_csv({path})",
    ".parquet": "read_parquet({path})",
    ".json": "read_json_auto({path})",
    ".jsonl": "read_json_auto({path}, format = 'newline_delimited')",
    ".ndjson": "read_json_auto({path}, format = 'newline_delimited')",
    ".xlsx": "read_xlsx({path}, header = true)",
}
FILE_KINDS = {
    ".csv": "CSV",
    ".tsv": "TSV",
    ".txt": "CSV",
    ".parquet": "Parquet",
    ".json": "JSON",
    ".jsonl": "JSON Lines",
    ".ndjson": "JSON Lines",
    ".xlsx": "Excel",
}


def convert_to_parquet(source: Path, target: Path) -> None:
    """Read an uploaded file (by its extension) and store it as one Parquet file."""
    extension = source.suffix.lower()
    reader = FILE_READERS[extension].format(path=quote_literal(source.as_posix()))
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        try:
            if extension == ".xlsx":
                con.execute("LOAD excel")
            con.execute(
                f"COPY (SELECT * FROM {reader}) TO {quote_literal(target.as_posix())} "
                "(FORMAT parquet, COMPRESSION zstd)"
            )
        except duckdb.Error as exc:
            target.unlink(missing_ok=True)
            raise AppError(
                f"Could not read this file as {FILE_KINDS[extension]}: {first_line(exc)}",
                code="file_unreadable",
            ) from None


def reserved_words() -> frozenset[str]:
    with duckdb.connect() as con:
        rows = con.execute(
            "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'"
        ).fetchall()
    return frozenset(row[0].lower() for row in rows)


def to_json_value(value: Any) -> Any:
    """Make a DuckDB value safe for JSON and for JavaScript numbers."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value if abs(value) <= JS_SAFE_INTEGER else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta | uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, list | tuple):
        return [to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    return str(value)


def first_line(error: BaseException) -> str:
    lines = str(error).strip().splitlines()
    return lines[0] if lines else type(error).__name__
