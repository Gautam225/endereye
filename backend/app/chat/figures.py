"""Charts drawn from numbers in documents, with every number checked against the documents.

When someone asks for a graph of what a document says, the model returns the chart's data. A
model can invent numbers, so each value (and each number in a key point) must appear in the
document passages it was shown, or in the question. A chart with a value that can't be found is
left out, and the answer says so, instead of showing made-up data.
"""

import json
import re
from bisect import bisect_left
from typing import Any

from pydantic import ValidationError

from app.chat.grounding import extract_figures
from app.chat.prompts import DocChart

MAX_CHARTS = 8  # a safety limit; the assistant draws only what the question needs
MAX_LABELS = 30
MAX_SERIES = 4
MAX_KEY_POINTS = 4
MAX_POINT_CHARS = 180


# A model often charts "7.9" for a document's "7,900,000" (millions), "79" for "7,900,000" in lakhs.
SCALES = (1.0, 1e3, 1e5, 1e6, 1e7, 1e9)


def _half_digit(value: float) -> float:
    """Half a unit of the last digit written: 0.5 for 7, 0.05 for 7.9, 0.005 for 3.15."""
    text = repr(float(value))
    decimals = len(text.split(".")[1].rstrip("0")) if "." in text and "e" not in text else 0
    return 0.5 * 10 ** (-decimals)


MAX_DERIVED_FROM = 60  # numbers whose sums and differences are also accepted


def numbers_in(texts: list[str]) -> list[float]:
    return [figure.value for text in texts for figure in extract_figures(text)]


class Allowed:
    """The numbers the documents and the question state, and ones that follow from them:
    the same number in another unit, and the sum or difference of two stated numbers."""

    def __init__(self, stated: list[float]) -> None:
        numbers = sorted(set(stated))
        head = numbers[:MAX_DERIVED_FROM]
        derived = {a + b for i, a in enumerate(head) for b in head[i:]}
        derived |= {abs(a - b) for i, a in enumerate(head) for b in head[i + 1 :]}
        self._numbers = sorted(set(numbers) | derived)

    def has(self, value: float, tolerance: float = 0.0) -> bool:
        for scale in SCALES:
            target = value * scale
            # In a larger unit the value is rounded: "3.15" stands for 3,150,000 give or take
            # half of its last written digit (5,000).
            room = tolerance * scale if scale == 1.0 else _half_digit(value) * scale
            room += 1e-9 * max(1.0, abs(target))
            low = bisect_left(self._numbers, target - room)
            if low < len(self._numbers) and self._numbers[low] <= target + room:
                return True
        return False


def _found(value: float, allowed: Allowed) -> bool:
    return allowed.has(value)


def _grounded_text(text: str, allowed: Allowed) -> bool:
    return all(allowed.has(f.value, f.tolerance) for f in extract_figures(text))


def clean_charts(
    charts: list[DocChart], sources: list[str], question: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """The charts that can be shown, and a note for each one that had to be left out."""
    allowed = Allowed(numbers_in([*sources, question]))
    accepted: list[dict[str, Any]] = []
    notes: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    for chart in charts[:MAX_CHARTS]:
        title = chart.title.strip()[:120] or "Chart"
        chart, dropped = _comparable(chart)
        notes += [
            f'Left out "{label}" from the chart "{title}": not every series states it.'
            for label in dropped
        ]
        problem = _problem(chart, allowed)
        if problem:
            notes.append(f'Left out the chart "{title}": {problem}')
            continue
        # The same picture twice (the AI sometimes gives a chart both ways) is drawn once.
        same = (
            chart.type,
            tuple(label.strip() for label in chart.labels),
            tuple(tuple(series.values) for series in chart.series),
        )
        if same in seen:
            continue
        seen.add(same)
        points = [
            point.strip()[:MAX_POINT_CHARS]
            for point in chart.key_points
            if point.strip() and _grounded_text(point, allowed)
        ][:MAX_KEY_POINTS]
        accepted.append(
            {
                "kind": "chart",
                "type": chart.type,
                "title": title,
                "x_label": chart.x_label.strip()[:60],
                "y_label": chart.y_label.strip()[:60],
                "labels": [label.strip()[:60] or "?" for label in chart.labels],
                "series": [
                    {"name": s.name.strip()[:60] or f"Series {i + 1}", "values": s.values}
                    for i, s in enumerate(chart.series)
                ],
                "key_points": points,
            }
        )
    return accepted, notes


_UNIT = re.compile(r"\(([^()]{1,20})\)\s*$")


def _complete_labels(chart: DocChart) -> list[int]:
    """Positions of the labels that every series has a value for."""
    return [
        i for i in range(len(chart.labels)) if all(s.values[i] is not None for s in chart.series)
    ]


def _comparable(chart: DocChart) -> tuple[DocChart, list[str]]:
    """When several series are compared, only the labels every series has a value for stay:
    a bar drawn for one document next to an empty space for the other compares nothing."""
    if len(chart.series) < 2 or any(len(s.values) != len(chart.labels) for s in chart.series):
        return chart, []
    keep = _complete_labels(chart)
    if len(keep) == len(chart.labels) or not keep:
        return chart, []  # nothing to trim, or nothing in common (refused below)
    dropped = [chart.labels[i] for i in range(len(chart.labels)) if i not in keep]
    series = [s.model_copy(update={"values": [s.values[i] for i in keep]}) for s in chart.series]
    trimmed = chart.model_copy(update={"labels": [chart.labels[i] for i in keep], "series": series})
    return trimmed, dropped


def _problem(chart: DocChart, allowed: Allowed) -> str | None:
    aligned = all(len(s.values) == len(chart.labels) for s in chart.series)
    if len(chart.series) > 1 and chart.labels and aligned and not _complete_labels(chart):
        return (
            "the series have no label with a value in every series (each document states "
            "different figures); chart only figures that every compared document states."
        )
    units = {m.group(1).strip().lower() for label in chart.labels if (m := _UNIT.search(label))}
    if len(units) > 1:
        return (
            f"it mixes units ({', '.join(sorted(units))}) on one axis; "
            "chart each unit in its own chart."
        )
    if not chart.labels or len(chart.labels) > MAX_LABELS:
        return f"it needs between 1 and {MAX_LABELS} labels."
    if not chart.series or len(chart.series) > MAX_SERIES:
        return f"it needs between 1 and {MAX_SERIES} series."
    if chart.type == "pie" and len(chart.series) != 1:
        return "a pie chart shows one series."
    for series in chart.series:
        if len(series.values) != len(chart.labels):
            return f'"{series.name}" does not have one value per label.'
        shown = [v for v in series.values if v is not None]
        if not shown:
            return f'"{series.name}" has no values.'
        if chart.type == "pie" and any(v < 0 for v in shown):
            return "a pie chart cannot show negative values."
        missing = [v for v in shown if not _found(v, allowed)]
        if missing:
            listed = ", ".join(f"{v:g}" for v in missing[:4])
            return f"these values are not in the documents: {listed}."
    return None


_FENCED = re.compile(r"```[a-zA-Z]*\s*(\{.*?\})\s*```", re.DOTALL)
_ORPHAN_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?\**(?:charts?|graphs?)\**:?\s*$", re.IGNORECASE)


def _chart_from(data: Any) -> DocChart | bool | None:
    """A DocChart when `data` is one; False when it is not chart-like at all."""
    if not (isinstance(data, dict) and "labels" in data and "series" in data):
        return False
    try:
        return DocChart.model_validate(data)
    except ValidationError:
        return None  # looks like a chart, but is not a usable one


def lift_charts(answer: str, charts: list[DocChart]) -> tuple[str, list[DocChart], int]:
    """Move chart data that the model wrote into its text into `charts`.

    Some models paste the chart as JSON in the reply instead of using the charts field, which
    would show as a block of code. Returns the reply without that JSON, the charts (those given
    plus the ones found), and how many found blocks could not be used.
    """
    found: list[DocChart] = []
    unusable = 0
    spans: list[tuple[int, int]] = []

    for match in _FENCED.finditer(answer):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        chart = _chart_from(data)
        if chart is False:
            continue
        spans.append(match.span())
        if chart is None:
            unusable += 1
        else:
            found.append(chart)  # type: ignore[arg-type]

    decoder = json.JSONDecoder()
    index = answer.find("{")
    while index != -1:
        if not any(start <= index < end for start, end in spans):
            try:
                data, end = decoder.raw_decode(answer, index)
            except ValueError:
                index = answer.find("{", index + 1)
                continue
            chart = _chart_from(data)
            if chart is not False:
                spans.append((index, end))
                if chart is None:
                    unusable += 1
                else:
                    found.append(chart)  # type: ignore[arg-type]
                index = answer.find("{", end)
                continue
        index = answer.find("{", index + 1)

    if not spans:
        return answer, charts, 0
    kept, last = [], 0
    for start, end in sorted(spans):
        kept.append(answer[last:start])
        last = end
    kept.append(answer[last:])
    lines = "".join(kept).splitlines()
    while lines and (not lines[-1].strip() or _ORPHAN_HEADING.match(lines[-1])):
        lines.pop()
    cleaned = [
        line
        for i, line in enumerate(lines)
        if not _ORPHAN_HEADING.match(line) or (i + 1 < len(lines) and lines[i + 1].strip())
    ]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    return text, [*charts, *found], unusable


_PLACEHOLDER = re.compile(
    r"^[\s(\[_*]*(?:see|refer to|find|view|check)\b[^\n]*\b(?:json|payload|chart data)\b[^\n]*$",
    re.IGNORECASE,
)


_INLINE_PLACEHOLDER = re.compile(
    r"\s*[(\[]\s*(?:see|refer to|find|view|check)\b[^)\]\n]*"
    r"\b(?:json|payload|chart data)\b[^)\]\n]*[)\]]",
    re.IGNORECASE,
)


def tidy_reply(text: str) -> str:
    """Remove the stand-in lines a model leaves where it thinks a chart goes ("Chart", "(See
    chart data in the JSON payload)"); the chart is drawn by the app, never written in the reply."""
    lines = [
        _INLINE_PLACEHOLDER.sub("", line).rstrip()
        for line in text.splitlines()
        if not _PLACEHOLDER.match(line) and not _ORPHAN_HEADING.match(line)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
