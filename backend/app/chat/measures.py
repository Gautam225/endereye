"""What a query's columns are, read from the SQL that produced them.

A result column called `total` might be a sum, a count or something else; the SELECT is the fact:
AVG(...) is an average whatever the column is named. The chart rules use this to keep a salary and
a head count off one axis, and the answer uses it to ask the database for the overall figures (the
same query without its grouping), because adding up the rows is wrong for an average or for a
distinct count.

Nothing here raises. When the SQL cannot be read the shape is "unknown" and callers fall back to
guessing from the column names.
"""

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

COUNT, SUM, AVG, MIN, MAX, RATIO, OTHER = "count", "sum", "avg", "min", "max", "ratio", "other"

MAX_DEPTH = 3  # CTE or derived-table levels followed to find where a column came from
_DIALECTS = {"postgresql": "postgres"}
_AGGREGATES: dict[type[exp.Expression], str] = {
    exp.Count: COUNT,
    exp.Sum: SUM,
    exp.Avg: AVG,
    exp.Min: MIN,
    exp.Max: MAX,
}
# Wrappers that only dress up the value inside: ROUND(AVG(x), 2), CAST(SUM(x) AS BIGINT).
_DRESSING = (exp.Alias, exp.Paren, exp.Cast, exp.Round, exp.Filter, exp.Coalesce)

# Words in a column name that say what kind of figure it is, strongest first.
_NAME_HINTS = (
    (AVG, {"avg", "average", "mean", "median"}),
    (COUNT, {"count", "cnt", "headcount", "number", "num", "qty", "quantity"}),
    (RATIO, {"pct", "percent", "percentage", "rate", "ratio", "share", "proportion"}),
    (MIN, {"min", "minimum", "lowest"}),
    (MAX, {"max", "maximum", "highest"}),
    (SUM, {"total", "sum", "expenditure", "spend", "spending"}),
)


def kind_from_name(name: str) -> str | None:
    """A guess from the name alone, used when the SQL does not say."""
    words = set(re.findall(r"[a-z]+", re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()))
    for kind, hints in _NAME_HINTS:
        if words & hints:
            return kind
    return None


@dataclass(frozen=True, slots=True)
class Shape:
    """What the SQL says about its result. Everything is empty when the SQL could not be read."""

    known: bool = False
    kinds: dict[str, str] = field(default_factory=dict)  # result column (lower case) -> kind
    ordered: bool = False  # the query has an ORDER BY of its own
    order_by: str | None = None  # the result column of its first sort key, lower case
    totals_sql: str | None = None  # the same query without its grouping: the overall figures
    totals_names: tuple[str, ...] = ()  # the columns that query returns, in order
    limit: int | None = None  # the query's LIMIT: when the rows reach it, some groups were cut
    filtered: bool = True  # the query has a WHERE, a HAVING or a join condition

    def kind_of(self, name: str) -> str | None:
        """What the column is: what the SQL says, else a guess from its name."""
        return self.kinds.get(name.lower()) or kind_from_name(name)


def analyse(sql: str | None, dialect: str = "duckdb") -> Shape:
    if not sql:
        return Shape()
    try:
        tree = sqlglot.parse_one(sql, read=_DIALECTS.get(dialect, dialect))
    except (sqlglot.errors.SqlglotError, RecursionError):
        return Shape()
    if not isinstance(tree, exp.Select):
        return Shape()  # a UNION or anything else: no claims
    names = [p.alias_or_name.lower() for p in tree.expressions]
    kinds = _kinds(tree, _ctes(tree), 0)
    ordered, order_by = _order(tree, names, set(kinds))
    totals_sql, totals_names, limit = _grand_totals(tree, _DIALECTS.get(dialect, dialect))
    filtered = any(tree.args.get(key) for key in ("where", "having")) or any(
        join.args.get("on") is not None for join in tree.args.get("joins") or []
    )
    return Shape(True, kinds, ordered, order_by, totals_sql, totals_names, limit, filtered)


# ── What each column is ──────────────────────────────────────────────────────


def _kind(node: exp.Expression) -> str | None:
    """count, sum, avg, min, max (an aggregate, however it is dressed), ratio (one aggregate over
    another), other (arithmetic on aggregates), or None for a plain column."""
    core = node
    while isinstance(core, _DRESSING) and core.this is not None:
        core = core.this
    for aggregate, kind in _AGGREGATES.items():
        if isinstance(core, aggregate):
            return kind
    if core.find(exp.AggFunc) is None:
        return None
    return RATIO if isinstance(core, exp.Div) else OTHER


def _ctes(tree: exp.Select) -> dict[str, exp.Select]:
    clause = tree.args.get("with_") or tree.args.get("with")
    found: dict[str, exp.Select] = {}
    for cte in clause.expressions if clause else []:
        if isinstance(cte.this, exp.Select):
            found[cte.alias.lower()] = cte.this
    return found


def _sources(select: exp.Select, ctes: dict[str, exp.Select]) -> list[exp.Select]:
    """The CTEs and derived tables this SELECT reads from."""
    parts = []
    clause = select.args.get("from_") or select.args.get("from")
    if clause is not None:
        parts.append(clause.this)
    parts += [join.this for join in select.args.get("joins") or []]
    found: list[exp.Select] = []
    for part in parts:
        if isinstance(part, exp.Table) and not part.args.get("db") and part.name.lower() in ctes:
            found.append(ctes[part.name.lower()])
        elif isinstance(part, exp.Subquery) and isinstance(part.this, exp.Select):
            found.append(part.this)
    return found


def _kinds(select: exp.Select, ctes: dict[str, exp.Select], depth: int) -> dict[str, str]:
    """Result column -> kind. A column passed through from a CTE or a derived table is whatever
    that query made it, so `SELECT * FROM stats` still tells its averages from its counts."""
    found: dict[str, str] = {}
    sources = _sources(select, ctes) if depth < MAX_DEPTH else []
    for projection in select.expressions:
        core = projection.unalias()
        if isinstance(core, exp.Star) or (
            isinstance(core, exp.Column) and isinstance(core.this, exp.Star)
        ):
            for source in sources:
                found.update(_kinds(source, ctes, depth + 1))
            continue
        name = projection.alias_or_name.lower()
        kind = _kind(core)
        if kind is None and isinstance(core, exp.Column):
            for source in sources:
                kind = _kinds(source, ctes, depth + 1).get(core.name.lower())
                if kind:
                    break
        if kind and name:
            found[name] = kind
    return found


# ── How the query is ordered ─────────────────────────────────────────────────


def _order(tree: exp.Select, names: list[str], passed_through: set[str]) -> tuple[bool, str | None]:
    """(whether the query sorts its rows, the result column of its first sort key).

    `passed_through` are the columns a `SELECT *` brings along, which `names` cannot list."""
    order = tree.args.get("order")
    if not order or not order.expressions:
        return False, None
    key = order.expressions[0].this
    if isinstance(key, exp.Literal) and key.is_int:  # ORDER BY 2
        position = int(key.name) - 1
        return True, names[position] if 0 <= position < len(names) else None
    if isinstance(key, exp.Column) and key.name.lower() in {*names, *passed_through}:
        return True, key.name.lower()
    for projection, name in zip(tree.expressions, names, strict=True):
        if projection.unalias().sql() == key.sql():  # ORDER BY AVG(salary) DESC
            return True, name
    return True, None


# ── The overall figures ──────────────────────────────────────────────────────


def _grand_totals(tree: exp.Select, dialect: str) -> tuple[str | None, tuple[str, ...], int | None]:
    """The same query without its grouping, which gives the overall figures exactly (an average of
    all the rows, a count of distinct values), or (None, (), None) when that cannot be done
    safely: no grouping, a HAVING or an OFFSET that picks some of the groups, window functions,
    subqueries, or a column that is neither a group key nor an aggregate. The third value is the
    query's LIMIT, which only matters if it cut groups off (the caller checks it against the
    number of rows)."""
    none: tuple[None, tuple[str, ...], None] = (None, (), None)
    group = tree.args.get("group")
    if not group:
        return none
    if any(group.args.get(key) for key in ("grouping_sets", "cube", "rollup", "totals")):
        return none
    if any(tree.args.get(key) for key in ("having", "offset", "qualify", "distinct")):
        return none
    limit = None
    if tree.args.get("limit") is not None:
        bound = tree.args["limit"].expression
        if not (isinstance(bound, exp.Literal) and bound.is_int):
            return none
        limit = int(bound.name)
    positions = {int(g.name) for g in group.expressions if isinstance(g, exp.Literal) and g.is_int}
    texts = {g.sql() for g in group.expressions}
    aliases = {g.name.lower() for g in group.expressions if isinstance(g, exp.Column)}

    kept: list[exp.Expression] = []
    for position, projection in enumerate(tree.expressions, start=1):
        core = projection.unalias()
        if core.find(exp.AggFunc) is not None:
            if core.find(exp.Window, exp.Select) is not None or not projection.alias:
                return none
            kept.append(projection.copy())
        elif not (
            group.args.get("all")  # GROUP BY ALL: everything that is not an aggregate
            or position in positions
            or core.sql() in texts
            or projection.alias_or_name.lower() in aliases
        ):
            return none
    if not kept:
        return none
    names = tuple(p.alias for p in kept)
    if len({n.lower() for n in names}) != len(names):
        return none
    totals = tree.copy()
    totals.set("expressions", kept)
    for key in ("group", "order", "having", "limit", "offset", "qualify"):
        totals.set(key, None)
    return totals.sql(dialect=dialect), names, limit
