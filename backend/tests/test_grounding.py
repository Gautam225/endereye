"""The numbers in a written answer must come from the result."""

import pytest

from app.chat.answer import clean_follow_ups, clean_title
from app.chat.grounding import (
    allowed_numbers,
    extract_figures,
    fallback_summary,
    fmt,
    numeric_totals,
    ungrounded_figures,
)

COLUMNS = [
    {"name": "region", "type": "VARCHAR"},
    {"name": "revenue", "type": "DOUBLE"},
    {"name": "orders", "type": "BIGINT"},
]
ROWS = [["East", 12345.5, 10], ["West", 8000.0, 7], ["North", 1500.25, 3]]


def allowed(question: str = "Revenue by region") -> list[float]:
    return allowed_numbers(question, COLUMNS, ROWS, ROWS)


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("Revenue was 12,345.5 in total", [12345.5]),
        ("up 12% to 1.2M", [12.0, 1_200_000.0]),
        ("about 3 lakh and 2 crore", [300_000.0, 20_000_000.0]),
        ("-5 and +7", [-5.0, 7.0]),
        ("in Q3 of FY26 for SKU-1043", [1043.0]),  # letters stuck to digits are not figures
        ("on 2025-03-01", [2025.0, 3.0, 1.0]),
        ("no numbers here", []),
    ],
)
def test_figures_are_read_from_text(text: str, values: list[float]) -> None:
    assert [f.value for f in extract_figures(text)] == values


def test_figures_that_are_in_the_data_are_accepted_even_when_rounded() -> None:
    summary = (
        "East leads with 12,345.5 (about 12.3k) across 10 orders. West has 8,000 from 7 orders. "
        "There are 3 regions and total revenue is 21,845.75, roughly 21.8k."
    )

    assert ungrounded_figures(summary, allowed()) == []


def test_a_figure_that_is_not_in_the_data_is_caught() -> None:
    bad = ungrounded_figures("East made 12,345.5, which is 56% of the total of 99,999.", allowed())

    assert bad == ["56%", "99,999"]


def test_a_percentage_may_be_a_fraction_in_the_data() -> None:
    columns = [{"name": "segment", "type": "VARCHAR"}, {"name": "share", "type": "DOUBLE"}]
    rows = [["A", 0.125], ["B", 0.875]]

    figures = allowed_numbers("Share by segment", columns, rows, rows)

    assert ungrounded_figures("Segment A has 12.5% and B has 87.5%.", figures) == []
    assert ungrounded_figures("Segment A has 14%.", figures) == ["14%"]


def test_numbers_from_the_question_and_the_row_count_are_allowed() -> None:
    figures = allowed_numbers("Show the top 2 regions in 2025", COLUMNS, ROWS[:2], ROWS)

    assert (
        ungrounded_figures("The top 2 regions in 2025 are East and West (3 rows).", figures) == []
    )
    assert ungrounded_figures("Over the last 90 days", figures) == ["90"]


def test_totals_cover_every_row_not_only_the_shown_ones() -> None:
    rows = [["x", float(i), i] for i in range(1, 101)]

    totals = numeric_totals(COLUMNS, rows)

    assert totals["revenue"] == {"sum": 5050.0, "min": 1.0, "max": 100.0, "average": 50.5}
    shown_only = allowed_numbers("q", COLUMNS, rows[:3], rows)
    assert ungrounded_figures("The total is 5,050 and the average 50.5", shown_only) == []


def test_numbers_are_formatted_plainly() -> None:
    assert (fmt(1234567.0), fmt(1234.5), fmt(0.1234), fmt(2.0)) == (
        "1,234,567",
        "1,234.5",
        "0.12",
        "2",
    )


def test_the_built_summary_only_uses_numbers_from_the_result() -> None:
    summary = fallback_summary(COLUMNS, ROWS)

    # every measure is described, not only the first one
    assert summary == (
        "3 rows, compared on 2 measures:\n"
        "- **Revenue**: highest East (12,345.5), lowest North (1,500.25).\n"
        "- **Orders**: highest East (10), lowest North (3).\n"
        "East leads on every measure."
    )
    assert ungrounded_figures(summary, allowed()) == []


def test_one_measure_keeps_the_short_summary() -> None:
    summary = fallback_summary(COLUMNS[:2], [row[:2] for row in ROWS])

    assert summary == "3 rows. Highest revenue: East (12,345.5); lowest: North (1,500.25)."


def test_the_built_summary_for_other_shapes() -> None:
    assert fallback_summary(COLUMNS, []) == "The query ran, but no rows matched."
    assert fallback_summary(COLUMNS[1:], [[1234.0, 5]]) == "Revenue: 1,234; Orders: 5."
    assert fallback_summary(COLUMNS, [["East", 5.0, 1]]) == "Revenue: 5; Orders: 1 for East."
    assert fallback_summary(COLUMNS[:1], [["a"], ["b"]]) == "2 rows with columns region."
    assert "first rows only" in fallback_summary(COLUMNS, ROWS, truncated=True)


def test_follow_ups_are_cleaned() -> None:
    items = [
        "  Show by month?  ",
        "show by month?",
        "Revenue by region?",
        "x" * 200,
        "",
        "What next?",
        "More?",
        "Extra?",
    ]

    assert clean_follow_ups(items, "revenue by region?") == [
        "Show by month?",
        "What next?",
        "More?",
    ]


def test_titles_are_short_and_plain() -> None:
    assert clean_title('  "Revenue   by region"  ') == "Revenue by region"
    assert len(clean_title("word " * 40)) <= 60
