"""Checks SQL before it is sent to an external PostgreSQL database.

This is the first wall. The second is the database login itself, which can only read the tables
an admin chose (it is checked read-only before every use), and the third is the read-only
transaction and timeouts the query runs in. None of them is trusted alone.

What the guard does, in order:

1. Parses the text as PostgreSQL. Exactly one statement, and it must be a query (SELECT, a
   WITH ... SELECT, or UNION of those). Anything else, including statements sqlglot can only
   read as a raw "command" (DO, SET, EXPLAIN ANALYZE ...), is refused.
2. Refuses anything that changes data or settings or locks rows, wherever it appears (so also
   inside a CTE or a sub-query), plus parameters, `SELECT INTO`, `FOR UPDATE`, casts to
   `regclass` and friends, and functions that name the session (current_user ...).
3. Function allow-list: a function that sqlglot does not know by name must be on a short list
   of harmless ones. `set_config`, `pg_read_file`, `dblink`, `query_to_xml` and every other
   unlisted function are refused. A block-list would miss the next dangerous function.
4. Tables: only the space's own tables, by their plain names. No schema, no catalogs, no
   `information_schema`. A name can only refer to a CTE of the query itself.
5. Columns: resolved against the columns the space lets the assistant see. A hidden column
   can't be named, and `SELECT *` expands only to the visible ones. A name that is not a
   column fails here, with a message the assistant can use to correct the query.
6. Rewrites the query so each table is its real, quoted `"schema"."table"`, and caps the row
   count. What is sent to the database is generated from the checked tree, not the text that
   was typed, and that generated text is checked once more.
"""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlglot.schema import MappingSchema

from app.engine.sql_guard import SqlNotAllowedError

DIALECT = "postgres"
MAX_SQL_CHARS = 20_000

# Statement kinds and clauses that must never appear anywhere in the tree. Names that this
# version of sqlglot does not have are skipped.
_DENIED_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterTable",
    "Command",
    "Copy",
    "Set",
    "SetItem",
    "Into",
    "Lock",
    "TruncateTable",
    "Transaction",
    "Commit",
    "Rollback",
    "Use",
    "Pragma",
    "Analyze",
    "Describe",
    "Declare",
    "Grant",
    "Revoke",
    "Kill",
    "Refresh",
    "LoadData",
    "Attach",
    "Detach",
    "Export",
    "Parameter",
    "Placeholder",
    "ObjectIdentifier",  # 'x'::regclass and similar casts read the system catalogs
    "CurrentUser",
    "SessionUser",
    "CurrentDatabase",
    "CurrentSchema",
    "CurrentSchemas",
    "CurrentVersion",
    "CurrentCatalog",
    "Semicolon",
)
DENIED_NODES: tuple[type[exp.Expression], ...] = tuple(
    node for name in _DENIED_NAMES if (node := getattr(exp, name, None)) is not None
)

# Functions that sqlglot does not turn into a typed node. Only these may be called by name.
# fmt: off
ALLOWED_FUNCTIONS = frozenset(
    {
        # dates and times
        "age", "date_part", "date_bin", "make_date", "make_time", "make_timestamp",
        "make_interval", "to_char", "to_date", "to_timestamp", "to_number", "isfinite",
        "justify_days", "justify_hours", "justify_interval", "timezone",
        # text
        "split_part", "btrim", "ltrim", "rtrim", "initcap", "lpad", "rpad", "left", "right",
        "repeat", "translate", "reverse", "concat_ws", "format", "starts_with", "strpos",
        "position", "overlay", "char_length", "character_length", "octet_length", "ascii", "chr",
        "regexp_replace", "regexp_count", "substr", "substring", "replace", "lower", "upper",
        "trim", "length", "concat",
        # numbers
        "abs", "ceil", "ceiling", "floor", "round", "trunc", "sign", "sqrt", "cbrt", "power",
        "pow", "exp", "ln", "log", "log10", "mod", "div", "degrees", "radians", "pi",
        "width_bucket", "greatest", "least", "scale", "min_scale", "gcd", "lcm",
        # aggregates and windows
        "count", "sum", "avg", "min", "max", "stddev", "stddev_pop", "stddev_samp", "variance",
        "var_pop", "var_samp", "corr", "covar_pop", "covar_samp", "regr_slope", "regr_intercept",
        "regr_r2", "bool_and", "bool_or", "every", "bit_and", "bit_or", "string_agg", "array_agg",
        "json_agg", "jsonb_agg", "percentile_cont", "percentile_disc", "mode", "any_value",
        "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
        "first_value", "last_value", "nth_value",
        # conditionals and checks
        "coalesce", "nullif",
        # arrays and json (reading only)
        "array_length", "cardinality", "array_to_string", "string_to_array", "array_position",
        "array_cat", "array_append", "array_prepend", "array_remove",
        "jsonb_extract_path", "jsonb_extract_path_text", "json_extract_path",
        "json_extract_path_text", "jsonb_array_length", "json_array_length", "jsonb_typeof",
        "json_typeof",
    }
)
# fmt: on

# Table-producing functions that touch nothing outside the query.
SAFE_TABLE_FUNCTIONS = frozenset({"generate_series", "unnest"})
# fmt: off
_GENERATED_ALIAS = re.compile(r"_col_\d+")
_REG_TYPES = frozenset(
    {
        "regclass", "regproc", "regprocedure", "regoper", "regoperator", "regtype", "regconfig",
        "regdictionary", "regnamespace", "regrole", "regcollation", "oid",
    }
)
# fmt: on


_GENERATE_SERIES = tuple(
    node
    for name in ("GenerateSeries", "ExplodingGenerateSeries")
    if (node := getattr(exp, name, None))
)


@dataclass(frozen=True, slots=True)
class AllowedTable:
    """One table of the space: the name used in SQL, where it really is, what may be read."""

    sql_name: str
    schema: str
    table: str
    columns: dict[str, str]  # visible column name -> type
    masked: tuple[str, ...] = ()  # visible columns whose values read as NULL for this person
    row_filter: str | None = None  # a condition: only the rows that meet it exist for this person


@dataclass(frozen=True, slots=True)
class CheckedSql:
    display: str  # what the person sees: their own table names
    run: str  # what is sent: real, quoted schema and table names, with a row cap


def _fail(message: str) -> SqlNotAllowedError:
    return SqlNotAllowedError(message)


def check_query(sql: str, tables: list[AllowedTable], max_rows: int) -> CheckedSql:
    """Returns the query ready to run, or raises SqlNotAllowedError with a plain reason."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise _fail("Write a query first.")
    if len(text) > MAX_SQL_CHARS:
        raise _fail(f"The query is too long (over {MAX_SQL_CHARS:,} characters).")

    query = _parse_one(text)
    _check_statement(query)
    by_name = {t.sql_name.lower(): t for t in tables}
    _check_tables(query, by_name)

    rewritten = _restrict(_qualify_and_rewrite(query.copy(), by_name), tables)
    run = _limited(rewritten, max_rows + 1).sql(dialect=DIALECT)
    _recheck(run, tables)
    return CheckedSql(display=text, run=run)


# ── 1. Parse ─────────────────────────────────────────────────────────────────


def _parse_one(text: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except SqlglotError as exc:
        errors = getattr(exc, "errors", None)
        reason = errors[0]["description"] if errors else "syntax error"
        raise _fail(f"The SQL could not be read: {reason}.") from None
    if len(statements) != 1 or isinstance(statements[0], exp.Block):
        raise _fail("Run one query at a time.")
    return statements[0]


def _check_statement(query: exp.Expression) -> None:
    if not isinstance(query, exp.Query):
        raise _fail("Only SELECT queries are allowed. Data and settings can't be changed here.")
    for node in query.walk():
        if isinstance(node, DENIED_NODES):
            raise _fail(_why_denied(node))
        if isinstance(node, exp.Cast | exp.TryCast) and _is_reg_type(node):
            raise _fail("Casting to a system type is not allowed.")
        if isinstance(node, exp.Anonymous | exp.AnonymousAggFunc):
            name = str(node.name).lower()
            if name not in ALLOWED_FUNCTIONS:
                raise _fail(f"The function {name}() is not available. Use standard SQL functions.")
        elif isinstance(node, exp.Table) and isinstance(node.this, exp.Func):
            name = _function_name(node.this)
            if name not in SAFE_TABLE_FUNCTIONS:
                raise _fail(f"{name}() is not allowed here. Query the space's tables.")


def _why_denied(node: exp.Expression) -> str:
    if isinstance(node, exp.Into):
        return "SELECT ... INTO creates a table, which is not allowed."
    if isinstance(node, exp.Lock):
        return "Locking rows (FOR UPDATE) is not allowed."
    if isinstance(node, exp.Parameter | exp.Placeholder):
        return "Write the values into the query; parameters like $1 or ? can't be used."
    if isinstance(node, exp.Command):
        return "This isn't a query that can run here. It should start with SELECT or WITH."
    kind = type(node).__name__
    if kind.startswith("Current") or kind == "SessionUser":
        return "Functions that name the session or the database are not allowed."
    return "Only SELECT queries are allowed. Data and settings can't be changed here."


def _is_reg_type(node: exp.Cast | exp.TryCast) -> bool:
    target = node.args.get("to")
    return isinstance(target, exp.DataType) and target.sql(dialect=DIALECT).lower() in _REG_TYPES


def _function_name(func: exp.Expression) -> str:
    if isinstance(func, exp.Anonymous):
        return str(func.name).lower()
    if isinstance(func, _GENERATE_SERIES):
        return "generate_series"
    return func.sql_name().lower()


# ── 4. Tables ────────────────────────────────────────────────────────────────


def _check_tables(query: exp.Expression, by_name: dict[str, AllowedTable]) -> None:
    ctes = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            continue  # a safe table function, checked above
        if table.args.get("db") or table.args.get("catalog"):
            raise _fail(
                f"Use the space's table names on their own (not '{table.sql(dialect=DIALECT)}'). "
                "System tables and other schemas can't be read."
            )
        name = table.name.lower()
        if name not in by_name and name not in ctes:
            available = ", ".join(sorted(by_name)) or "none yet"
            raise _fail(
                f"There is no table called '{table.name}' in this space. Tables: {available}."
            )


# ── 5-6. Columns and the rewrite ─────────────────────────────────────────────


def _qualify_and_rewrite(query: exp.Expression, by_name: dict[str, AllowedTable]) -> exp.Expression:
    # Column names are matched exactly as listed: unquoted names are lowercased by PostgreSQL,
    # so a column with capitals has to be quoted, in the query and here.
    schema = MappingSchema(
        {t.sql_name: dict(t.columns) for t in by_name.values()},
        dialect=DIALECT,
        normalize=False,
    )
    try:
        qualified = qualify(
            query,
            schema=schema,
            dialect=DIALECT,
            validate_qualify_columns=True,
            identify=False,
        )
    except SqlglotError as exc:
        raise _fail(_column_message(str(exc), by_name)) from None

    # qualify() names unnamed result columns _col_0, _col_1. Give them back PostgreSQL's own
    # names, but only in the outermost SELECT, where nothing refers to them.
    if isinstance(qualified, exp.Select):
        for alias in [a for a in qualified.expressions if isinstance(a, exp.Alias)]:
            if _GENERATED_ALIAS.fullmatch(alias.alias or ""):
                alias.replace(alias.this)

    # A table named where a column belongs is a reference to the whole row, hidden columns included.
    if any(isinstance(node, exp.TableColumn) for node in qualified.walk()):
        raise _fail("Selecting a whole table row isn't allowed. List the columns you need.")
    scopes = traverse_scope(qualified)
    _resolve_unqualified(qualified, scopes, by_name)

    seen: set[int] = set()
    for scope in scopes:
        for node, source in scope.selected_sources.values():
            if not isinstance(node, exp.Table) or not isinstance(node.this, exp.Identifier):
                continue  # a sub-query, or a table function that was checked above
            seen.add(id(node))
            if isinstance(source, exp.Table):  # a real table, not a CTE or sub-query
                _point_at_real_table(node, by_name)
    for node in qualified.find_all(exp.Table):
        if isinstance(node.this, exp.Identifier) and id(node) not in seen:
            raise _fail("This query uses a table in a way that can't be checked.")
    return qualified


def _restrict(query: exp.Expression, tables: list[AllowedTable]) -> exp.Expression:
    """Put each table that has a row filter or a masked column behind a sub-query that holds only
    what this person may read. It sits in front of the real table wherever the query names it, so
    it holds for joins, CTEs and sub-queries alike. The condition was vetted when it was written."""
    guarded = {(t.schema, t.table): t for t in tables if t.masked or t.row_filter}
    if not guarded:
        return query
    for node in list(query.find_all(exp.Table)):
        table = guarded.get((node.db, node.name))
        if table is None or not isinstance(node.this, exp.Identifier):
            continue
        inner = exp.select(
            *(_projection(name, kind, table) for name, kind in table.columns.items())
        )
        inner = inner.from_(
            exp.Table(
                this=exp.to_identifier(table.table, quoted=True),
                db=exp.to_identifier(table.schema, quoted=True),
            )
        )
        if table.row_filter:
            inner = inner.where(sqlglot.parse_one(table.row_filter, read=DIALECT))
        alias = node.alias or table.sql_name
        node.replace(
            exp.Subquery(
                this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias, quoted=True))
            )
        )
    return query


def _projection(name: str, kind: str, table: AllowedTable) -> exp.Expression:
    column = exp.column(name, quoted=True)
    if name not in table.masked:
        return column
    try:
        empty: exp.Expression = exp.cast(exp.Null(), exp.DataType.build(kind, dialect=DIALECT))
    except SqlglotError:
        empty = exp.Null()
    return exp.alias_(empty, name, quoted=True)


def _resolve_unqualified(
    query: exp.Expression, scopes: list[Scope], by_name: dict[str, AllowedTable]
) -> None:
    """Give every column a table, checking that the table really offers it.

    qualify() leaves some bare names alone because it takes them for output aliases (in HAVING,
    in ORDER BY expressions ...), and PostgreSQL would read those as the real columns, hidden
    ones included. So no bare name is trusted: it must be a visible column of exactly one table
    in scope, or the whole of an ORDER BY item that is an output name (which PostgreSQL reads as
    the output column). Anything else, including a whole-row reference like `SELECT people
    FROM people`, is refused."""
    scope_of = {id(scope.expression): scope for scope in scopes}
    for column in list(query.find_all(exp.Column)):
        if column.table or isinstance(column.this, exp.Star):
            continue
        owner = column.find_ancestor(exp.Select, exp.SetOperation)
        if owner is not None and _is_output_name(column, owner):
            continue
        scope = scope_of.get(id(owner)) if isinstance(owner, exp.Select) else None
        found: list[str] = []
        while scope is not None and not found:
            found = _offered_by(scope, column.name, by_name)
            scope = scope.parent
        if not found:
            raise _fail(_column_message(f"Column '{column.name}' could not be resolved", by_name))
        if len(found) > 1:
            raise _fail(
                f"The column '{column.name}' is ambiguous: name its table, like {found[0]}."
                f"{column.name}."
            )
        column.set("table", exp.to_identifier(found[0]))


def _is_output_name(column: exp.Column, owner: exp.Expression) -> bool:
    item = column.parent
    return (
        isinstance(item, exp.Ordered)
        and isinstance(item.parent, exp.Order)
        and item.parent is owner.args.get("order")
        and column.name in owner.named_selects
    )


def _offered_by(scope: Scope, name: str, by_name: dict[str, AllowedTable]) -> list[str]:
    """The sources (by alias) in this scope that have a column called `name`."""
    found = []
    for alias, (_node, source) in scope.selected_sources.items():
        if isinstance(source, exp.Table):
            table = by_name.get(source.name.lower())
            offered = list(table.columns) if table else []
        else:
            offered = list(getattr(source.expression, "named_selects", []))
        if name in offered:
            found.append(alias)
    return found


def _point_at_real_table(node: exp.Table, by_name: dict[str, AllowedTable]) -> None:
    allowed = by_name.get(node.name.lower())
    if allowed is None:
        raise _fail(f"There is no table called '{node.name}' in this space.")
    alias = node.alias or allowed.sql_name
    node.set("this", exp.to_identifier(allowed.table, quoted=True))
    node.set("db", exp.to_identifier(allowed.schema, quoted=True))
    node.set("catalog", None)
    node.set("alias", exp.TableAlias(this=exp.to_identifier(alias, quoted=True)))


def _column_message(error: str, by_name: dict[str, AllowedTable]) -> str:
    match = re.search(r"Column '([^']+)' could not be resolved|Unknown column: (\S+)", error)
    if match:
        wanted = match.group(1) or match.group(2)
        for table in by_name.values():
            for column in table.columns:
                if column != wanted and column.lower() == wanted.lower():
                    return (
                        f'The column "{column}" has capital letters, so write it in double '
                        f'quotes: "{column}".'
                    )
        available = "; ".join(
            f"{t.sql_name}({', '.join(t.columns)})"
            for t in sorted(by_name.values(), key=lambda t: t.sql_name)
        )
        return (
            f"The column '{wanted}' is not available (or is ambiguous: name its table, "
            f"like orders.id). Columns: {available}."
        )
    return "The query could not be checked against the space's tables and columns."


# ── Row cap and the final check ──────────────────────────────────────────────


def _limited(query: exp.Expression, cap: int) -> exp.Expression:
    """At most `cap` rows. A smaller LIMIT in the query stays."""
    if isinstance(query, exp.Select):
        limit = query.args.get("limit")
        count = limit.expression if isinstance(limit, exp.Limit) else None
        if isinstance(count, exp.Literal) and count.is_int and int(count.this) <= cap:
            return query
        if limit is None or isinstance(limit, exp.Limit):
            return query.limit(cap)
    return exp.select("*").from_(query.subquery("_q")).limit(cap)


def _recheck(run: str, tables: list[AllowedTable]) -> None:
    """The text sent to the database is parsed once more: it must still be one query that only
    reads the real tables of the space."""
    real = {(t.schema, t.table) for t in tables}
    try:
        again = sqlglot.parse_one(run, read=DIALECT)
    except SqlglotError:
        raise _fail("The query could not be prepared safely.") from None
    if not isinstance(again, exp.Query):
        raise _fail("The query could not be prepared safely.")
    ctes = {cte.alias_or_name for cte in again.find_all(exp.CTE)}
    for node in again.walk():
        if isinstance(node, DENIED_NODES):
            raise _fail("The query could not be prepared safely.")
        if (
            isinstance(node, exp.Table)
            and not isinstance(node.this, exp.Func)
            and (node.db, node.name) not in real
            and not (not node.db and node.name in ctes)
        ):
            raise _fail("The query could not be prepared safely.")
