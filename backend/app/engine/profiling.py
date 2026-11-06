"""Profiling: per-column statistics, searchable values, and join detection.

Runs on the same locked-down DuckDB connection as queries (see duckdb_engine). All functions
here are blocking; call them from a worker thread.
"""

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import duckdb

from app.engine.duckdb_engine import (
    Column,
    QueryFailedError,
    QueryTimeoutError,
    TableSource,
    first_line,
    open_views,
    quote_identifier,
    to_json_value,
)

# Limits for searchable ("entity matching") values, the same as Databricks Genie's.
VALUE_INDEX_MAX_DISTINCT = 1024
VALUE_INDEX_MAX_LENGTH = 127
VALUE_INDEX_MAX_COLUMNS = 120  # per space

TOP_VALUES = 5
SHOWN_VALUE_LENGTH = 100  # longer values are cut for display
MAX_JOIN_CANDIDATES = 60
MIN_JOIN_OVERLAP = 0.8  # share of the smaller key set that must also appear in the other


@dataclass(slots=True)
class ColumnProfile:
    name: str
    stats: dict[str, Any]
    values: list[str] | None = None  # every distinct value, only when the column is searchable


@dataclass(frozen=True, slots=True)
class TableProfile:
    row_count: int
    columns: list[ColumnProfile]


@dataclass(frozen=True, slots=True)
class JoinCandidate:
    left: str
    left_column: str
    right: str
    right_column: str


@dataclass(frozen=True, slots=True)
class DetectedJoin:
    left: str
    left_column: str
    right: str
    right_column: str
    relationship: str


@dataclass(frozen=True, slots=True)
class JoinTable:
    name: str
    columns: list[Column]


def is_text(type_name: str) -> bool:
    return type_name.upper() == "VARCHAR"


def _is_simple(type_name: str) -> bool:
    """Types whose values can be compared, counted and shown as text."""
    upper = type_name.upper()
    return not any(word in upper for word in ("STRUCT", "MAP", "UNION", "BLOB", "[", "LIST"))


def _shown(value: Any) -> str:
    text = str(to_json_value(value))
    return text if len(text) <= SHOWN_VALUE_LENGTH else text[: SHOWN_VALUE_LENGTH - 1] + "…"


def _guarded[T](
    con: duckdb.DuckDBPyConnection,
    timeout_seconds: float,
    action: Callable[[duckdb.DuckDBPyConnection], T],
) -> T:
    """Run `action` on the connection with a time limit, then close it."""
    timer = threading.Timer(timeout_seconds, con.interrupt)
    timer.start()
    try:
        return action(con)
    except duckdb.InterruptException:
        raise QueryTimeoutError(
            f"This took longer than {timeout_seconds:g} seconds and was stopped."
        ) from None
    except duckdb.Error as exc:
        raise QueryFailedError(f"Could not read the table: {first_line(exc)}") from None
    finally:
        timer.cancel()
        con.close()


def profile_table(
    source: TableSource, columns: list[Column], *, timeout_seconds: float
) -> TableProfile:
    """Row count and, for each column: nulls, distinct count, min/max, most common values.

    A text column with 1 to 1,024 distinct values, none longer than 127 characters, also comes
    back with all of them (`values`), so they can be made searchable.
    """
    table = quote_identifier(source.name)

    def run(con: duckdb.DuckDBPyConnection) -> TableProfile:
        parts = ["count(*)"]
        for column in columns:
            name = quote_identifier(column.name)
            parts.append(f"count({name})")
            if _is_simple(column.type):
                parts += [
                    f"count(DISTINCT {name})",
                    f"min({name})::VARCHAR",
                    f"max({name})::VARCHAR",
                    f"max(length({name}))" if is_text(column.type) else "NULL",
                ]
            else:
                parts += ["NULL", "NULL", "NULL", "NULL"]
        row = con.execute(f"SELECT {', '.join(parts)} FROM {table}").fetchone()
        row_count = int(row[0])
        profiles = []
        for index, column in enumerate(columns):
            non_null, distinct, low, high, longest = row[1 + index * 5 : 6 + index * 5]
            nulls = row_count - int(non_null)
            stats: dict[str, Any] = {
                "null_count": nulls,
                "null_pct": round(100 * nulls / row_count, 2) if row_count else 0.0,
                "distinct_count": None if distinct is None else int(distinct),
                "min": None if low is None else _shown(low),
                "max": None if high is None else _shown(high),
                "top_values": [],
                "searchable": False,
            }
            values = None
            if _is_simple(column.type) and non_null:
                name = quote_identifier(column.name)
                top = con.execute(
                    f"SELECT {name}::VARCHAR, count(*) FROM {table} WHERE {name} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_VALUES}"
                ).fetchall()
                stats["top_values"] = [{"value": _shown(v), "count": int(n)} for v, n in top]
                if (
                    is_text(column.type)
                    and 0 < distinct <= VALUE_INDEX_MAX_DISTINCT
                    and longest <= VALUE_INDEX_MAX_LENGTH
                ):
                    stats["searchable"] = True
                    values = _distinct(con, table, name)
            profiles.append(ColumnProfile(column.name, stats, values))
        return TableProfile(row_count, profiles)

    return _guarded(open_views([source]), timeout_seconds, run)


def distinct_values(source: TableSource, column: str, *, timeout_seconds: float) -> list[str]:
    """All distinct text values of one column (the caller has checked it is searchable)."""
    table, name = quote_identifier(source.name), quote_identifier(column)
    return _guarded(open_views([source]), timeout_seconds, lambda con: _distinct(con, table, name))


def _distinct(con: duckdb.DuckDBPyConnection, table: str, name: str) -> list[str]:
    rows = con.execute(
        f"SELECT DISTINCT {name} FROM {table} WHERE {name} IS NOT NULL ORDER BY 1"
    ).fetchall()
    return [row[0] for row in rows]


# ── Join detection ───────────────────────────────────────────────────────────

_INTEGER = re.compile(r"^U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?$")


def _key_family(type_name: str) -> str | None:
    upper = type_name.upper()
    if _INTEGER.fullmatch(upper):
        return "integer"
    if upper in {"VARCHAR", "UUID"}:
        return upper.lower()
    return None  # floats, dates, booleans and nested types make poor join keys


def _singular(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    return name[:-1] if name.endswith("s") else name


def _is_key_name(column: str, other_table: str, other_column: str) -> bool:
    """`orders.customer_id` -> `customers.id`, or the same column name in both tables."""
    column, other_table, other_column = column.lower(), other_table.lower(), other_column.lower()
    if column == other_column:
        return True
    return other_column == "id" and column in {f"{other_table}_id", f"{_singular(other_table)}_id"}


def join_candidates(tables: list[JoinTable]) -> list[JoinCandidate]:
    """Column pairs in different tables that could be a join key, judged by name and type."""
    found: list[JoinCandidate] = []
    for a, b in combinations(tables, 2):
        for ca in a.columns:
            for cb in b.columns:
                family = _key_family(ca.type)
                if family is None or family != _key_family(cb.type):
                    continue
                if _is_key_name(ca.name, b.name, cb.name) or _is_key_name(cb.name, a.name, ca.name):
                    found.append(JoinCandidate(a.name, ca.name, b.name, cb.name))
    return found[:MAX_JOIN_CANDIDATES]


def detect_joins(
    sources: list[TableSource], tables: list[JoinTable], *, timeout_seconds: float
) -> list[DetectedJoin]:
    """Keep the candidates whose values really line up, and say how the tables relate.

    A candidate needs a unique key on at least one side (many-to-many pairs are not joins an
    analyst wants by default) and most of the smaller key set present in the other table.
    The "many" side is always returned as the left table.
    """
    candidates = join_candidates(tables)
    if not candidates:
        return []

    def run(con: duckdb.DuckDBPyConnection) -> list[DetectedJoin]:
        found = []
        for c in candidates:
            lt, lc = quote_identifier(c.left), quote_identifier(c.left_column)
            rt, rc = quote_identifier(c.right), quote_identifier(c.right_column)
            row = con.execute(
                f"WITH l AS (SELECT DISTINCT {lc} AS v FROM {lt} WHERE {lc} IS NOT NULL), "
                f"r AS (SELECT DISTINCT {rc} AS v FROM {rt} WHERE {rc} IS NOT NULL) "
                "SELECT (SELECT count(*) FROM l), (SELECT count(*) FROM r), "
                "(SELECT count(*) FROM l JOIN r USING (v)), "
                f"(SELECT count({lc}) FROM {lt}), (SELECT count({rc}) FROM {rt})"
            ).fetchone()
            left_distinct, right_distinct, overlap, left_rows, right_rows = map(int, row)
            smaller = min(left_distinct, right_distinct)
            if smaller < 2 or overlap < MIN_JOIN_OVERLAP * smaller:
                continue
            left_unique, right_unique = left_rows == left_distinct, right_rows == right_distinct
            if left_unique and right_unique:
                found.append(
                    DetectedJoin(c.left, c.left_column, c.right, c.right_column, "one_to_one")
                )
            elif right_unique:
                found.append(
                    DetectedJoin(c.left, c.left_column, c.right, c.right_column, "many_to_one")
                )
            elif left_unique:  # flip, so the "many" side is on the left
                found.append(
                    DetectedJoin(c.right, c.right_column, c.left, c.left_column, "many_to_one")
                )
        return found

    return _guarded(open_views(sources), timeout_seconds, run)
