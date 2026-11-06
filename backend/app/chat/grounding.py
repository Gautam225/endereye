"""Checking that the numbers in a written answer really come from the query result.

The model writes the summary, but it may only use figures that are in the data it was shown.
Every number in the summary is compared with the result (its cells, its totals, its row count,
and the numbers in the question). A summary with a number that can't be found is thrown away
and replaced by one built directly from the result, so an answer never states an invented figure.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.chat.charts import breakdown_groups, is_numeric, pretty, result_roles, suggest_chart
from app.chat.measures import Shape

MULTIPLIERS = {
    "k": 1e3,
    "thousand": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "m": 1e6,
    "million": 1e6,
    "crore": 1e7,
    "crores": 1e7,
    "b": 1e9,
    "billion": 1e9,
}
_NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-+]?)(?P<digits>\d[\d,]*(?:\.\d+)?)"
    r"(?P<suffix>%|\s?(?:percent|thousand|lakhs?|million|crores?|billion)\b|[kKmMbB]\b)?"
)


@dataclass(frozen=True, slots=True)
class Figure:
    text: str
    value: float
    tolerance: float  # half a unit of the last digit written, so "12.3" matches 12.34
    percent: bool = False


def extract_figures(text: str) -> list[Figure]:
    figures = []
    for match in _NUMBER.finditer(text):
        digits = match.group("digits").replace(",", "")
        try:
            number = float(digits)
        except ValueError:
            continue
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        suffix = (match.group("suffix") or "").strip().lower()
        percent = suffix in {"%", "percent"}
        scale = MULTIPLIERS.get(suffix, 1.0)
        value = (-number if match.group("sign") == "-" else number) * scale
        figures.append(
            Figure(match.group(0).strip(), value, 0.5 * 10 ** (-decimals) * scale, percent)
        )
    return figures


def _numbers_in_cell(value: Any) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int | float):
        return [float(value)]
    if isinstance(value, str):
        return [f.value for f in extract_figures(value)]
    return []


def numeric_totals(
    columns: list[dict[str, Any]], rows: list[list[Any]]
) -> dict[str, dict[str, float]]:
    """Sum, smallest, largest and average of each numeric column, over every row."""
    totals: dict[str, dict[str, float]] = {}
    for index, column in enumerate(columns):
        if not is_numeric(column["type"]):
            continue
        values = [
            float(r[index])
            for r in rows
            if isinstance(r[index], int | float) and not isinstance(r[index], bool)
        ]
        if values:
            totals[column["name"]] = {
                "sum": sum(values),
                "min": min(values),
                "max": max(values),
                "average": sum(values) / len(values),
            }
    return totals


def allowed_numbers(
    question: str,
    columns: list[dict[str, Any]],
    shown_rows: list[list[Any]],
    all_rows: list[list[Any]],
    overall: dict[str, float] | None = None,
) -> list[float]:
    measures = sum(1 for c in columns if is_numeric(c["type"]))  # "compared on 3 measures"
    allowed = [float(len(all_rows)), float(len(shown_rows)), float(len(columns)), float(measures)]
    allowed += [f.value for f in extract_figures(question)]
    allowed += list((overall or {}).values())  # the database's own overall figures
    for row in shown_rows:
        for cell in row:
            allowed += _numbers_in_cell(cell)
    for stats in numeric_totals(columns, all_rows).values():
        allowed += list(stats.values())
    return allowed


def _matches(figure: Figure, allowed: list[float]) -> bool:
    for number in allowed:
        if abs(figure.value - number) <= figure.tolerance + 1e-9 * abs(number):
            return True
        if figure.percent and abs(figure.value - number * 100) <= figure.tolerance:
            return True  # 0.125 shown as 12.5%
    return False


def ungrounded_figures(summary: str, allowed: list[float]) -> list[str]:
    """Numbers written in the summary that are not in the data."""
    return [f.text for f in extract_figures(summary) if not _matches(f, allowed)]


# ── A summary built straight from the result ─────────────────────────────────


def fmt(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


_OVERALL_LABELS = frozenset({"overall", "total", "all", "average", "everyone", "sum"})


def _percent(part: float, whole: float) -> str:
    share = abs(part / whole) * 100
    return "less than 0.1%" if 0 < share < 0.05 else f"{share:.1f}%"


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def describe_analysis(title: str, kind: str, pairs: list[tuple[str, float]]) -> str:
    """One natural sentence or two about one analysis. Every figure is read from its own rows; the
    only arithmetic is the plain difference and share between two of them."""
    name = title.strip().lower()
    if len(pairs) == 1:
        label, value = pairs[0]
        if label.lower() in _OVERALL_LABELS:
            return _capital(f"the {label.lower()} {name} is {fmt(value)}.")
        return f"{label} has {fmt(value)}."
    if kind == "line":
        ordered = sorted(pairs, key=lambda p: p[0])
        (first, start), (last, end) = ordered[0], ordered[-1]
        peak = max(pairs, key=lambda p: p[1])
        verb = "rose" if end > start else "fell" if end < start else "stayed level"
        change = f" ({_percent(end - start, start)})" if start and end != start else ""
        return (
            f"{len(pairs)} points from {first} to {last}. It {verb} from {fmt(start)} to "
            f"{fmt(end)}{change}; the highest point is {peak[0]} ({fmt(peak[1])})."
        )
    ranked = sorted(pairs, key=lambda p: p[1], reverse=True)
    (top, high), (bottom, low) = ranked[0], ranked[-1]
    if high == low:
        return f"every value is the same, {fmt(high)}."
    gap = high - low
    more = f", about {_percent(gap, low)} more" if low else ""
    if len(ranked) == 2:
        return (
            f"{top} is higher ({fmt(high)}) than {bottom} ({fmt(low)}), a gap of {fmt(gap)}{more}."
        )
    order = ", ".join(f"{label} {fmt(value)}" for label, value in ranked[:6])
    rest = f" and {len(ranked) - 6} more" if len(ranked) > 6 else ""
    return (
        f"{top} is highest at {fmt(high)} and {bottom} lowest at {fmt(low)}, a gap of "
        f"{fmt(gap)}{more}. In order: {order}{rest}."
    )


def annotate_panels(
    columns: list[dict[str, Any]], rows: list[list[Any]], spec: dict[str, Any]
) -> None:
    """Give each chart of a stacked result a plain sentence about what it shows."""
    for panel, pairs in breakdown_groups(columns, rows, spec):
        if pairs and panel["type"] != "kpi":
            panel["note"] = _capital(describe_analysis(panel["value"], panel["type"], pairs))


def _breakdown_summary(
    columns: list[dict[str, Any]], rows: list[list[Any]], spec: dict[str, Any]
) -> str:
    """A result that holds several analyses, in plain words: what each one shows."""
    lines = [
        f"- **{panel['value']}**: {describe_analysis(panel['value'], panel['type'], pairs)}"
        for panel, pairs in breakdown_groups(columns, rows, spec)
        if pairs
    ]
    return (
        f"The result holds {len(lines)} separate analyses. Here is what each one shows:\n"
        + "\n".join(lines)
        + "\nEach analysis has its own chart below, and the Table view has every row."
    )


def _overall(kind: str | None, value: float) -> str:
    """How an overall figure reads after a semicolon."""
    match kind:
        case "avg":
            return f"overall average {fmt(value)}"
        case "min":
            return f"overall lowest {fmt(value)}"
        case "max":
            return f"overall highest {fmt(value)}"
        case "ratio" | "other":
            return f"overall {fmt(value)}"
        case _:
            return f"total {fmt(value)}"


def _label(row: list[Any], label_cols: list[int]) -> str:
    parts = [str(row[i]) for i in label_cols if row[i] is not None]
    return " / ".join(parts) if parts else "(empty)"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _compare_summary(
    columns: list[dict[str, Any]],
    rows: list[list[Any]],
    measures: list[str],
    label_cols: list[int],
    more: str,
    shape: Shape,
    totals: dict[str, float],
) -> str:
    """Every measure of a grouped result: who is highest and lowest on it, its overall figure
    (asked of the database, never added up here), and who leads on what. Every number is read
    from the rows or from that overall query."""
    index = {c["name"]: i for i, c in enumerate(columns)}
    lines: list[str] = []
    leaders: dict[str, list[str]] = {}
    for name in measures:
        i = index[name]
        valued = [r for r in rows if isinstance(r[i], int | float) and not isinstance(r[i], bool)]
        if not valued:
            continue
        title = pretty(name)
        high, low = max(valued, key=lambda r: r[i]), min(valued, key=lambda r: r[i])
        if high[i] == low[i]:
            text = f"{fmt(high[i])} in every row"
        else:
            tied = sum(1 for r in valued if r[i] == high[i]) > 1
            text = (
                f"highest {_label(high, label_cols)} ({fmt(high[i])}{', tied' if tied else ''}), "
                f"lowest {_label(low, label_cols)} ({fmt(low[i])})"
            )
            if not tied:
                leaders.setdefault(_label(high, label_cols), []).append(title.lower())
        if name in totals:
            text += f"; {_overall(shape.kind_of(name), totals[name])}"
        lines.append(f"- **{title}**: {text}.")
    head = f"{count_rows(rows)}{more}, compared on {plural(len(lines), 'measure')}:"
    out = [head, *lines]
    if len(lines) >= 2 and leaders:
        if len(leaders) == 1 and len(next(iter(leaders.values()))) == len(lines):
            out.append(f"{next(iter(leaders))} leads on every measure.")
        else:
            out.append(
                "; ".join(f"{who} leads on {_join(what)}" for who, what in leaders.items()) + "."
            )
    return "\n".join(out)


def count_rows(rows: list[list[Any]]) -> str:
    return f"{len(rows):,} row{'s' if len(rows) != 1 else ''}"


def fallback_summary(
    columns: list[dict[str, Any]],
    rows: list[list[Any]],
    truncated: bool = False,
    shape: Shape | None = None,
    totals: dict[str, float] | None = None,
) -> str:
    """A plain description whose every number is read from the result (and, for the overall
    figures, from the database's own answer to the same query without its grouping)."""
    if not rows:
        return "The query ran, but no rows matched."
    shape, totals = shape or Shape(), totals or {}
    measures = [
        i
        for i, c in enumerate(columns)
        if is_numeric(c["type"]) and isinstance(rows[0][i], int | float)
    ]
    labels = [i for i, c in enumerate(columns) if not is_numeric(c["type"])]
    count = len(rows)
    more = " (the first rows only)" if truncated else ""
    spec = suggest_chart(columns, rows, shape)
    if spec and spec.get("facet") and spec.get("panels"):
        return _breakdown_summary(columns, rows, spec)
    if count == 1 and measures:
        parts = [f"{pretty(columns[i]['name'])}: {fmt(rows[0][i])}" for i in measures[:3]]
        label = f" for {rows[0][labels[0]]}" if labels and rows[0][labels[0]] is not None else ""
        return f"{'; '.join(parts)}{label}."
    roles = result_roles(columns, rows)
    by = [i for i, c in enumerate(columns) if c["name"] in roles["dimension"] + roles["time"]]
    if len(roles["measure"]) >= 2 and by:
        return _compare_summary(columns, rows, roles["measure"], by[:2], more, shape, totals)
    if measures and labels:
        m, label = measures[0], labels[0]
        valued = [r for r in rows if isinstance(r[m], int | float)]
        if valued:
            high, low = max(valued, key=lambda r: r[m]), min(valued, key=lambda r: r[m])
            name = columns[m]["name"].replace("_", " ")
            text = (
                f"{count:,} rows{more}. Highest {name}: {high[label]} ({fmt(high[m])}); "
                f"lowest: {low[label]} ({fmt(low[m])})."
            )
            if columns[m]["name"] in totals:
                kind = shape.kind_of(columns[m]["name"])
                text += f" Across all rows: {_overall(kind, totals[columns[m]['name']])}."
            return text
    names = ", ".join(c["name"] for c in columns[:6])
    return f"{count:,} row{'s' if count != 1 else ''}{more} with columns {names}."
