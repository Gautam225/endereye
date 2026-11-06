"""Picking a chart for a query result, by rules. A table is the answer when no chart fits.

A chart spec is plain data that the frontend draws from the real result rows:

    {"type": "bar", "x": "region", "y": ["revenue"], "series": None, "title": "Revenue by region"}

Rules come first because they are instant, free and predictable. Nothing here invents values:
a spec only names columns that exist in the result.

One chart per analysis, chosen by the data and not by the person. Three things keep a chart honest:

- A result that stacks several separate analyses (a column naming the analysis, a label and a
  value, for example "Gender: F, M" and "Birth year: 1952, 1953 ...") is drawn as one chart per
  analysis (`panels`), never as one chart that puts genders and years on the same axis.
- Figures of different kinds never share an axis. An average salary, a head count and a total
  salary bill each get a chart of their own (`panels`, one per measure), even when their sizes
  happen to be close. What kind a column is comes from the SQL (measures.py). Nothing is dropped
  silently: a measure that gets no chart is named in `omitted`.
- Categories are laid out to be read: bars lie down (`orientation`) when there are many or their
  names are long, and are ranked, largest first (`sort`), unless the query sorted them itself.
"""

import re
from typing import Any

from app.chat.measures import OTHER, Shape

CHART_TYPES = ("bar", "line", "area", "pie", "scatter", "kpi")
MAX_CATEGORIES = 30
MAX_SERIES = 8
MAX_MEASURES = 4
MAX_PIE_SLICES = 6
MAX_TITLE = 120
MAX_PANELS = 6  # separate analyses stacked in one result, or measures that get a chart each
MAX_SCALE_GAP = 30  # measures further apart than this are not drawn together
# A measure column that says nothing, so a chart is named after what it shows instead.
GENERIC_MEASURES = frozenset({"value", "values", "metric", "result", "measure", "number"})
HORIZONTAL_FROM = 5  # a bar chart of this many categories lies down, so every name can be read
HORIZONTAL_LABEL = 10  # ... and so does one with a name longer than this many characters
MAX_GROUPED_X = 16  # a period axis with up to this many points, split by a few groups, is bars
MAX_GROUPED_SERIES = 4

# The lookahead stops "INTERVAL" matching "INT", and a list such as "INTEGER[]" matching "INTEGER".
_NUMERIC = re.compile(
    r"^(U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?|DOUBLE|FLOAT|REAL|DECIMAL)(?![\w\[])", re.I
)
_TEMPORAL = re.compile(r"^(DATE|TIMESTAMP(_S|_MS|_NS)?|TIME|DATETIME)(?![\w\[])", re.I)
_ID_LIKE = re.compile(r"(^|_)(id|key|code|zip|pincode|phone)$", re.I)
_TIME_NAME = re.compile(r"(^|_)(year|month|quarter|week|day|date|period|yr|fy|fiscal_year)$", re.I)
_SHARE_NAME = re.compile(r"share|percent|pct|proportion|ratio|mix|split", re.I)
_DATE_TEXT = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$|^\d{4}-Q[1-4]$|^[A-Z][a-z]{2} \d{4}$")


def is_numeric(type_name: str) -> bool:
    return bool(_NUMERIC.match(type_name))


def is_temporal(type_name: str) -> bool:
    return bool(_TEMPORAL.match(type_name))


# Short forms that read badly on a chart.
_WORDS = {
    "cnt": "count",
    "qty": "quantity",
    "amt": "amount",
    "num": "number",
    "pct": "percent",
    "avg": "average",
    "tot": "total",
}
_COMBINED = re.compile(
    r"\b(combined?|combining|together|side[- ]by[- ]side|(in|on) (one|a single|the same) "
    r"(graph|chart|plot)|single (graph|chart))\b",
    re.IGNORECASE,
)


def pretty(name: str) -> str:
    """'employee_cnt' -> 'Employee count'."""
    words = [_WORDS.get(word.lower(), word) for word in name.replace("_", " ").split()]
    text = " ".join(words)
    return text[:1].upper() + text[1:] if text else name


def wants_combined(question: str) -> bool:
    """True when the person asks for several things to be drawn together in one chart."""
    return bool(_COMBINED.search(question))


def _roles(columns: list[dict[str, Any]], rows: list[list[Any]]) -> dict[str, list[str]]:
    """Which columns are times, measures (numbers to add up or compare) and dimensions."""
    roles: dict[str, list[str]] = {"time": [], "measure": [], "dimension": []}
    for index, column in enumerate(columns):
        name, type_name = column["name"], column["type"]
        values = [r[index] for r in rows if r[index] is not None]
        if is_temporal(type_name) or (
            _TIME_NAME.search(name) and (is_numeric(type_name) or _text_dates(values))
        ):
            roles["time"].append(name)
        elif is_numeric(type_name) and not _ID_LIKE.search(name):
            roles["measure"].append(name)
        elif type_name.upper() == "VARCHAR" and _text_dates(values) and len(set(values)) > 1:
            roles["time"].append(name)
        else:
            roles["dimension"].append(name)
    return roles


def _text_dates(values: list[Any]) -> bool:
    sample = values[:50]
    return bool(sample) and all(isinstance(v, str) and _DATE_TEXT.match(v) for v in sample)


def _distinct(columns: list[dict[str, Any]], rows: list[list[Any]], name: str) -> int:
    index = next(i for i, c in enumerate(columns) if c["name"] == name)
    return len({str(r[index]) for r in rows})


def _size(columns: list[dict[str, Any]], rows: list[list[Any]], name: str) -> float:
    index = next(i for i, c in enumerate(columns) if c["name"] == name)
    return max((abs(r[index]) for r in rows if isinstance(r[index], int | float)), default=0)


def _kind(shape: Shape, name: str) -> str | None:
    """count, sum, avg, min, max or ratio; None when nothing says what the figure is."""
    kind = shape.kind_of(name)
    return None if kind == OTHER else kind


def _share_axis(
    columns: list[dict[str, Any]], rows: list[list[Any]], shape: Shape, first: str, other: str
) -> bool:
    """Two measures share an axis only when they are the same kind of figure (two counts, two
    sums, two averages) and about the same size. An average salary and a head count are not
    comparable even when their sizes happen to be close, and a figure of a known kind is never
    drawn against one that nothing identifies."""
    if _kind(shape, first) != _kind(shape, other):
        return False
    a, b = _size(columns, rows, first), _size(columns, rows, other)
    return a == 0 or b == 0 or 1 / MAX_SCALE_GAP <= b / a <= MAX_SCALE_GAP


def _measure_groups(
    columns: list[dict[str, Any]], rows: list[list[Any]], measures: list[str], shape: Shape
) -> list[list[str]]:
    """The measures that can share a chart, grouped, in the order the query lists them. Every
    measure lands in a group: none is dropped because it differs from the first."""
    groups: list[list[str]] = []
    for name in measures:
        for group in groups:
            if len(group) < MAX_MEASURES and _share_axis(columns, rows, shape, group[0], name):
                group.append(name)
                break
        else:
            groups.append([name])
    return groups


def _is_time_labels(labels: list[str]) -> bool:
    return len(labels) >= 3 and all(
        re.fullmatch(r"\d{4}", label) or _DATE_TEXT.match(label) for label in labels
    )


def _breakdowns(
    columns: list[dict[str, Any]], rows: list[list[Any]], dims: list[str]
) -> tuple[str, str, list[str]] | None:
    """(column naming the analysis, label column, the analyses) when the rows are several
    separate analyses stacked together, else None.

    They are stacked when each analysis has its own labels: no label appears under two analyses,
    and none twice within one. That is what tells them from an ordinary grouped result (year by
    gender), where the same labels repeat under every group.
    """
    if len(dims) < 2:
        return None
    index = {c["name"]: i for i, c in enumerate(columns)}
    for facet in sorted(dims, key=lambda d: _distinct(columns, rows, d)):
        names = list(dict.fromkeys(str(r[index[facet]]) for r in rows))
        if not 2 <= len(names) <= MAX_PANELS:
            continue
        for label in dims:
            if label == facet:
                continue
            labels: dict[str, list[str]] = {name: [] for name in names}
            for r in rows:
                labels[str(r[index[facet]])].append(str(r[index[label]]))
            every = [item for group in labels.values() for item in group]
            clean = (
                len(set(every)) == len(every)  # no repeats, no overlap
                and max(len(group) for group in labels.values()) >= 2
                and all(len(group) <= MAX_CATEGORIES for group in labels.values())
            )
            if clean:
                return facet, label, names
    return None


def breakdown_groups(
    columns: list[dict[str, Any]], rows: list[list[Any]], spec: dict[str, Any]
) -> list[tuple[dict[str, Any], list[tuple[str, float]]]]:
    """For a spec with panels: each panel with its (label, value) pairs, from the real rows."""
    index = {c["name"]: i for i, c in enumerate(columns)}
    facet, label, value = index[spec["facet"]], index[spec["x"]], index[spec["y"][0]]
    groups = []
    for panel in spec["panels"]:
        pairs = [
            (str(r[label]), float(r[value]))
            for r in rows
            if str(r[facet]) == panel["value"] and isinstance(r[value], int | float)
        ]
        groups.append((panel, pairs))
    return groups


def _title(measures: list[str], by: str | None) -> str:
    what = ", ".join(pretty(m) for m in measures[:2])
    return f"{what} by {by.replace('_', ' ')}" if by else what


def result_roles(columns: list[dict[str, Any]], rows: list[list[Any]]) -> dict[str, list[str]]:
    """Which columns are times, measures (numbers to compare) and dimensions (what they are by)."""
    return _roles(columns, rows)


def _horizontal(kind: str, labels: list[str]) -> bool:
    """Bars lie down when there are many categories or their names are long, so every name can
    be read without tilting your head."""
    return (
        kind == "bar"
        and bool(labels)
        and (
            len(labels) >= HORIZONTAL_FROM or max(len(label) for label in labels) > HORIZONTAL_LABEL
        )
    )


def _ranked(shape: Shape, group: list[str], measures: list[str]) -> bool:
    """Whether the bars of a one-measure chart go in order, largest first. Not when the query
    sorted them itself by anything but another measure (an alphabetical list, or the smallest
    first, is what was asked for), and not when the SQL is not known."""
    if len(group) != 1 or not shape.known:
        return False
    if not shape.ordered:
        return True
    return shape.order_by in {m.lower() for m in measures} and shape.order_by != group[0].lower()


def suggest_chart(
    columns: list[dict[str, Any]], rows: list[list[Any]], shape: Shape | None = None
) -> dict[str, Any] | None:
    """A chart spec, or None when a table says it better. `shape` is what the SQL says about the
    columns (measures.analyse); without it the kind of each figure is guessed from its name."""
    if not rows or not columns:
        return None
    shape = shape or Shape()
    roles = _roles(columns, rows)
    times, dims, found = roles["time"], roles["dimension"], roles["measure"]
    if not found:
        return None
    drawn = found[:MAX_PANELS]
    index = {c["name"]: i for i, c in enumerate(columns)}

    def labels_of(name: str) -> list[str]:
        return list(dict.fromkeys(str(r[index[name]]) for r in rows))

    def build(
        kind: str,
        x: str | None,
        groups: list[list[str]],
        *,
        series: str | None = None,
        by: str | None = None,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """A chart for each group of measures. `categories` are the labels of an x axis that is
        not a time: those bars lie down when there are many, and are ranked when they can be."""
        groups = groups[:MAX_PANELS]
        shown = {name for group in groups for name in group}
        by = by or x
        rank = categories is not None and series is None

        def one(group: list[str]) -> dict[str, Any]:
            part: dict[str, Any] = {"y": group, "title": _title(group, by), "type": kind}
            if rank and _ranked(shape, group, found):
                part["sort"] = "value"
            return part

        first = one(groups[0])
        spec: dict[str, Any] = {
            "type": kind,
            "x": x,
            "y": groups[0],
            "series": series,
            "title": first["title"],
        }
        if categories is not None and _horizontal(kind, categories):
            spec["orientation"] = "horizontal"
        if "sort" in first:
            spec["sort"] = "value"
        if len(groups) > 1:
            spec["panels"] = [one(group) for group in groups]
        if left_out := [name for name in found if name not in shown]:
            spec["omitted"] = left_out
        return spec

    if len(rows) == 1:
        label = dims[0] if len(dims) == 1 and not times else None
        tiles: dict[str, Any] = {
            "type": "kpi",
            "x": label,
            "y": drawn,
            "series": None,
            "title": _title(drawn, label),
        }
        if found[MAX_PANELS:]:
            tiles["omitted"] = found[MAX_PANELS:]
        return tiles

    if times:
        x = times[0]
        if len(rows) < 3:
            return None
        series = next((d for d in dims if 2 <= _distinct(columns, rows, d) <= MAX_SERIES), None)
        if series:
            # A few periods (years, months) split by a few groups read best as grouped bars:
            # one bar per group for each period. Many periods are a trend, so a line each.
            grouped = (
                _distinct(columns, rows, x) <= MAX_GROUPED_X
                and _distinct(columns, rows, series) <= MAX_GROUPED_SERIES
            )
            return build(
                "bar" if grouped else "line",
                x,
                [[name] for name in drawn],
                series=series,
                by=f"{x} and {series}",
            )
        return build("line", x, _measure_groups(columns, rows, drawn, shape))

    stacked = _breakdowns(columns, rows, dims) if dims and len(dims) >= 2 else None
    if stacked:
        facet, label, names = stacked
        measure = found[0]
        panels = []
        for name in names:
            labels = [str(r[index[label]]) for r in rows if str(r[index[facet]]) == name]
            # One value alone is a number to read, not a chart to draw.
            kind = "kpi" if len(labels) == 1 else "line" if _is_time_labels(labels) else "bar"
            title = name if measure.lower() in GENERIC_MEASURES else None
            panels.append(
                {
                    "value": name,
                    "title": title or f"{pretty(measure)} by {name.lower()}",
                    "type": kind,
                }
            )
        spec = {
            "type": "bar",
            "x": label,
            "y": [measure],
            "series": None,
            "title": _title([measure], label),
            "facet": facet,
            "panels": panels,
        }
        if len(found) > 1:
            spec["omitted"] = found[1:]
        return spec

    if dims:
        if len(dims) >= 2:
            small = [d for d in dims if 2 <= _distinct(columns, rows, d) <= MAX_SERIES]
            # The smaller group is the series (one bar each); the other one is the axis.
            series = min(small, key=lambda d: _distinct(columns, rows, d)) if small else None
            x = next((d for d in dims if d != series), None)
            if series is None or x is None or _distinct(columns, rows, x) > MAX_CATEGORIES:
                return None
            return build(
                "bar",
                x,
                [[name] for name in drawn],
                series=series,
                by=f"{x} and {series}",
                categories=labels_of(x),
            )
        x = dims[0]
        categories = _distinct(columns, rows, x)
        if categories > MAX_CATEGORIES or categories < 2:
            return None
        first = index[drawn[0]]
        non_negative = all((r[first] is None) or r[first] >= 0 for r in rows)
        if (
            len(drawn) == 1
            and categories <= MAX_PIE_SLICES
            and non_negative
            and _SHARE_NAME.search(drawn[0])
        ):
            return {"type": "pie", "x": x, "y": drawn, "series": None, "title": _title(drawn, x)}
        groups = _measure_groups(columns, rows, drawn, shape)
        return build("bar", x, groups, categories=labels_of(x))

    if len(found) >= 2 and len(rows) >= 5:
        return {
            "type": "scatter",
            "x": found[0],
            "y": [found[1]],
            "series": None,
            "title": f"{pretty(found[1])} vs {found[0].replace('_', ' ')}",
        }
    return None


class ChartError(ValueError):
    """A chart the user asked for can't be drawn from this result."""


def validate_chart(spec: dict[str, Any], columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Check a chart spec (for example one edited by a person) against the result's columns."""
    types = {c["name"]: c["type"] for c in columns}
    kind = spec.get("type")
    if kind not in CHART_TYPES:
        raise ChartError(f"Chart type must be one of: {', '.join(CHART_TYPES)}.")
    x, series = spec.get("x"), spec.get("series")
    y = spec.get("y") or []
    if not isinstance(y, list) or not y or len(y) > MAX_MEASURES:
        raise ChartError(f"Choose between 1 and {MAX_MEASURES} columns for the values.")
    for name in [x, series, *y]:
        if name is not None and name not in types:
            raise ChartError(f"There is no column called '{name}' in this result.")
    if any(not is_numeric(types[name]) for name in y):
        raise ChartError("The values must be numeric columns.")
    if kind != "kpi" and x is None:
        raise ChartError("Choose a column for the X axis.")
    if kind == "scatter" and not is_numeric(types[x]):
        raise ChartError("A scatter chart needs a numeric X axis.")
    if kind == "pie" and len(y) != 1:
        raise ChartError("A pie chart shows one value column.")
    if series is not None and kind in {"pie", "kpi", "scatter"}:
        series = None
    title = str(spec.get("title") or "").strip()[:MAX_TITLE]
    return {"type": kind, "x": x, "y": list(y), "series": series, "title": title}
