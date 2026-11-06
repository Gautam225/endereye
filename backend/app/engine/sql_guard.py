"""Checks SQL before it runs: exactly one read-only query that only uses the space's tables.

This is the first wall. The second is the DuckDB connection itself, which can only read the
space's own files and cannot change its settings (see duckdb_engine.py).
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.errors import AppError

# Table functions that don't touch files.
SAFE_TABLE_FUNCTIONS = frozenset({"range", "generate_series", "unnest"})
# Functions that read or list files, run other SQL, or reveal settings.
BLOCKED_PREFIXES = ("read_", "parquet_", "delta_", "iceberg_", "sniff_", "duckdb_", "pragma_")
BLOCKED_FUNCTIONS = frozenset({"glob", "query", "query_table", "getenv", "current_setting"})
# Words a SQL statement can start with. Anything else is most likely a typo.
STATEMENT_KEYWORDS = frozenset(
    [
        "select",
        "with",
        "from",
        "values",
        "table",
        "pivot",
        "unpivot",
        "summarize",
        "insert",
        "update",
        "delete",
        "merge",
        "create",
        "drop",
        "alter",
        "truncate",
        "copy",
        "attach",
        "detach",
        "pragma",
        "set",
        "reset",
        "show",
        "describe",
        "explain",
        "use",
        "begin",
        "commit",
        "rollback",
        "install",
        "load",
        "call",
        "export",
        "import",
        "vacuum",
        "checkpoint",
        "grant",
        "revoke",
        "comment",
    ]
)


class SqlNotAllowedError(AppError):
    status_code = 400
    code = "sql_not_allowed"


def _function_name(func: exp.Func) -> str:
    return (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()


def check_query(sql: str, allowed_tables: set[str], dialect: str = "duckdb") -> str:
    """Returns the query, ready to run, or raises SqlNotAllowedError with a plain reason."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise SqlNotAllowedError("Write a query first.")
    try:
        statements = [s for s in sqlglot.parse(text, read=dialect) if s is not None]
    except ParseError as exc:
        reason = exc.errors[0]["description"] if exc.errors else "syntax error"
        raise SqlNotAllowedError(f"The SQL could not be read: {reason}.") from None
    if len(statements) != 1:
        raise SqlNotAllowedError("Run one query at a time.")
    query = statements[0]
    first_word = re.match(r"\(*\s*([A-Za-z_]+)", text)
    if first_word is None or first_word.group(1).lower() not in STATEMENT_KEYWORDS:
        raise SqlNotAllowedError(
            "This isn't a query that can run here. Check the spelling: it should start with "
            "SELECT or WITH."
        )
    if not isinstance(query, exp.Query):
        raise SqlNotAllowedError(
            "Only SELECT queries are allowed. Data and settings can't be changed from here."
        )

    allowed = {name.lower() for name in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            name = _function_name(table.this)
            if name in SAFE_TABLE_FUNCTIONS:
                continue
            raise SqlNotAllowedError(f"{name}() is not allowed here. Query the space's tables.")
        if table.args.get("db") or table.args.get("catalog"):
            raise SqlNotAllowedError(
                f"Use the space's table names on their own (not '{table.sql(dialect=dialect)}')."
            )
        if table.name.lower() not in allowed | cte_names:
            available = ", ".join(sorted(allowed)) or "none yet"
            raise SqlNotAllowedError(
                f"There is no table called '{table.name}' in this space. Tables: {available}."
            )

    for func in query.find_all(exp.Func):
        name = _function_name(func)
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_PREFIXES):
            raise SqlNotAllowedError(f"The function {name}() is not allowed.")
    return text
