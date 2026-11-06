"""Is the assistant's answer the right one? Compare two query results, not two pieces of SQL.

A query can run without error and still answer the wrong question, and two different queries
can answer the same one. So a benchmark compares what the reference SQL returns with what the
assistant's SQL returns:

- Values, not names: a column called `revenue` and one called `total` are the same if they hold
  the same values. The assistant may also put the columns in another order.
- Numbers are equal when they agree to about nine significant digits (so 0.1 + 0.2 equals 0.3,
  and 90 equals 90.0).
- Rows are compared as a set, unless the question is marked as one where the row order is part
  of the answer (a ranking), in which case the order has to match too.
- Anything else is a difference. The reason says what differs but never quotes values: a
  stored benchmark result must not copy rows of the database into this app.
"""

import itertools
import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.engine.duckdb_engine import QueryResult

MAX_PERMUTED_COLUMNS = 6  # columns are matched by value; more than this must be in the same order

Cell = Any
Row = tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Verdict:
    correct: bool
    reason: str = ""  # why not, in words; empty when correct


def _cell(value: Any) -> Cell:
    if value is None:
        return value
    if isinstance(value, bool):
        return f"bool:{value}"  # not equal to 1 or 0, as Python's True == 1 would have it
    if isinstance(value, int | float):
        number = float(value)
        return float(f"{number:.9g}") if math.isfinite(number) else str(number)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list | dict):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _rows(result: QueryResult) -> list[Row]:
    return [tuple(_cell(v) for v in row) for row in result.rows]


def _signature(rows: list[Row], column: int) -> tuple[tuple[str, str], ...]:
    """A column's values as a sorted list, to tell which columns could be the same one."""
    return tuple(sorted((type(r[column]).__name__, repr(r[column])) for r in rows))


def _matches(expected: list[Row], actual: list[Row], ordered: bool) -> bool:
    return expected == actual if ordered else Counter(expected) == Counter(actual)


def _reordered(actual: list[Row], order: tuple[int, ...]) -> list[Row]:
    return [tuple(row[i] for i in order) for row in actual]


def compare_results(expected: QueryResult, actual: QueryResult, *, ordered: bool) -> Verdict:
    """Whether `actual` answers the same question as `expected`."""
    if expected.truncated or actual.truncated:
        return Verdict(False, "There are too many rows to compare. Make the reference smaller.")
    want, got = _rows(expected), _rows(actual)
    wanted_columns, got_columns = len(expected.columns), len(actual.columns)
    if wanted_columns != got_columns:
        return Verdict(
            False,
            f"The result has {got_columns} column{'s' if got_columns != 1 else ''}; "
            f"the reference has {wanted_columns}.",
        )
    if len(want) != len(got):
        return Verdict(
            False,
            f"The result has {len(got):,} row{'s' if len(got) != 1 else ''}; "
            f"the reference has {len(want):,} row{'s' if len(want) != 1 else ''}.",
        )

    if _matches(want, got, ordered):
        return Verdict(True)
    # The same values may be in other columns: try the columns in another order.
    if wanted_columns <= MAX_PERMUTED_COLUMNS and want:
        wanted_signatures = [_signature(want, i) for i in range(wanted_columns)]
        got_signatures = [_signature(got, j) for j in range(got_columns)]
        options = [
            [j for j, sig in enumerate(got_signatures) if sig == wanted_signatures[i]]
            for i in range(wanted_columns)
        ]
        if all(options):
            for order in itertools.product(*options):
                if len(set(order)) == wanted_columns and _matches(
                    want, _reordered(got, order), ordered
                ):
                    return Verdict(True)

    if ordered and Counter(want) == Counter(got):
        return Verdict(False, "The rows are right but in a different order than the reference.")
    missing = sum((Counter(want) - Counter(got)).values())
    extra = sum((Counter(got) - Counter(want)).values())
    if missing or extra:
        return Verdict(
            False,
            f"{missing:,} of the {len(want):,} reference rows are missing from the result, "
            f"and {extra:,} rows are not in the reference.",
        )
    return Verdict(False, "The values differ from the reference.")
