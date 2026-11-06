"""Chart choice by rules, and checking a chart someone edited."""

import pytest

from app.chat.charts import ChartError, is_numeric, is_temporal, suggest_chart, validate_chart


def cols(**types: str) -> list[dict[str, str]]:
    return [{"name": name, "type": type_name} for name, type_name in types.items()]


def test_a_category_and_a_number_is_a_bar_chart() -> None:
    columns = cols(region="VARCHAR", revenue="DOUBLE")
    rows = [["East", 10.0], ["West", 25.5], ["North", 7.0]]

    assert suggest_chart(columns, rows) == {
        "type": "bar",
        "x": "region",
        "y": ["revenue"],
        "series": None,
        "title": "Revenue by region",
    }


def test_time_and_numbers_is_a_line_chart_with_up_to_four_series() -> None:
    columns = cols(month="DATE", revenue="DOUBLE", orders="BIGINT")
    rows = [["2025-01-01", 1.0, 3], ["2025-02-01", 2.0, 5], ["2025-03-01", 3.0, 4]]

    chart = suggest_chart(columns, rows)

    assert chart is not None
    assert (chart["type"], chart["x"], chart["y"], chart["series"]) == (
        "line",
        "month",
        ["revenue", "orders"],
        None,
    )


def test_a_few_periods_and_a_small_category_make_grouped_bars_one_per_category() -> None:
    columns = cols(month="DATE", region="VARCHAR", revenue="DOUBLE")
    rows = [[f"2025-0{m}-01", r, float(m)] for m in (1, 2, 3) for r in ("East", "West")]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["type"] == "bar" and chart["series"] == "region"
    assert chart["y"] == ["revenue"]


def test_a_year_stored_as_a_number_is_time_not_a_measure() -> None:
    columns = cols(year="INTEGER", revenue="DOUBLE")
    rows = [[2023, 1.0], [2024, 2.0], [2025, 3.0]]

    chart = suggest_chart(columns, rows)

    assert chart is not None and (chart["type"], chart["x"], chart["y"]) == (
        "line",
        "year",
        ["revenue"],
    )


def test_text_months_are_recognised_as_time() -> None:
    columns = cols(period="VARCHAR", revenue="DOUBLE")
    rows = [["2025-01", 1.0], ["2025-02", 2.0], ["2025-03", 3.0]]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["type"] == "line"


def test_a_single_row_is_a_kpi_tile() -> None:
    chart = suggest_chart(cols(total="DOUBLE", orders="BIGINT"), [[1234.5, 60]])

    assert chart == {
        "type": "kpi",
        "x": None,
        "y": ["total", "orders"],
        "series": None,
        "title": "Total, Orders",
    }
    labelled = suggest_chart(cols(region="VARCHAR", total="DOUBLE"), [["East", 5.0]])
    assert labelled is not None and labelled["x"] == "region"


def test_shares_of_a_few_categories_are_a_pie_but_other_numbers_are_bars() -> None:
    rows = [["A", 0.5], ["B", 0.3], ["C", 0.2]]

    pie = suggest_chart(cols(segment="VARCHAR", share_pct="DOUBLE"), rows)
    bar = suggest_chart(cols(segment="VARCHAR", revenue="DOUBLE"), rows)
    negative = suggest_chart(
        cols(segment="VARCHAR", share_pct="DOUBLE"), [["A", 0.5], ["B", -0.1], ["C", 0.2]]
    )

    assert pie is not None and pie["type"] == "pie"
    assert bar is not None and bar["type"] == "bar"
    assert negative is not None and negative["type"] == "bar"  # a pie can't show a negative


def test_two_categories_make_a_grouped_bar() -> None:
    columns = cols(region="VARCHAR", product="VARCHAR", revenue="DOUBLE")
    rows = [[r, p, 1.0] for r in ("East", "West", "North") for p in ("Laptop", "Webcam")]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["type"] == "bar"
    assert chart["series"] in {"product", "region"} and chart["x"] != chart["series"]


def test_two_numbers_and_nothing_else_is_a_scatter_plot() -> None:
    columns = cols(price="DOUBLE", quantity="BIGINT")
    rows = [[float(i), i * 2] for i in range(8)]

    chart = suggest_chart(columns, rows)

    assert chart is not None and (chart["type"], chart["x"], chart["y"]) == (
        "scatter",
        "price",
        ["quantity"],
    )
    assert suggest_chart(columns, rows[:3]) is None  # too few points to say anything


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        (cols(region="VARCHAR", revenue="DOUBLE"), []),  # nothing to draw
        (cols(name="VARCHAR", note="VARCHAR"), [["a", "b"], ["c", "d"]]),  # no numbers
        (
            cols(customer_id="BIGINT", name="VARCHAR"),
            [[1, "a"], [2, "b"]],
        ),  # an id is not a measure
        (
            cols(customer="VARCHAR", spend="DOUBLE"),
            [[f"c{i}", float(i)] for i in range(80)],  # too many bars to read
        ),
        (cols(region="VARCHAR", revenue="DOUBLE"), [["East", 1.0], ["East", 2.0]]),  # one category
        (
            cols(month="DATE", revenue="DOUBLE"),
            [["2025-01-01", 1.0], ["2025-02-01", 2.0]],
        ),  # 2 points
    ],
    ids=["empty", "no-numbers", "id-column", "too-many-categories", "one-category", "two-points"],
)
def test_no_chart_when_a_table_is_clearer(columns, rows) -> None:
    assert suggest_chart(columns, rows) is None


def test_a_chart_only_names_columns_that_exist() -> None:
    columns = cols(region="VARCHAR", product="VARCHAR", revenue="DOUBLE", orders="BIGINT")
    rows = [["East", "Laptop", 1.0, 2], ["West", "Webcam", 3.0, 4], ["North", "Laptop", 5.0, 6]]

    chart = suggest_chart(columns, rows)

    assert chart is not None
    used = [chart["x"], chart["series"], *chart["y"]]
    assert all(name is None or name in {c["name"] for c in columns} for name in used)


# ── Editing a chart ──────────────────────────────────────────────────────────

RESULT = cols(region="VARCHAR", revenue="DOUBLE", orders="BIGINT", day="DATE")


def test_an_edited_chart_is_checked_against_the_columns() -> None:
    ok = validate_chart(
        {"type": "line", "x": "day", "y": ["revenue", "orders"], "title": "  Trend  "}, RESULT
    )

    assert ok == {
        "type": "line",
        "x": "day",
        "y": ["revenue", "orders"],
        "series": None,
        "title": "Trend",
    }
    assert (
        validate_chart(
            {"type": "bar", "x": "region", "y": ["revenue"], "series": "region"}, RESULT
        )["series"]
        == "region"
    )
    pie = validate_chart(
        {"type": "pie", "x": "region", "y": ["revenue"], "series": "region"}, RESULT
    )
    assert pie["series"] is None  # series makes no sense for a pie


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"type": "radar", "x": "region", "y": ["revenue"]}, "Chart type"),
        ({"type": "bar", "x": "nope", "y": ["revenue"]}, "no column called 'nope'"),
        ({"type": "bar", "x": "region", "y": ["region"]}, "numeric"),
        ({"type": "bar", "x": "region", "y": []}, "between 1 and 4"),
        ({"type": "bar", "y": ["revenue"]}, "X axis"),
        ({"type": "scatter", "x": "region", "y": ["revenue"]}, "numeric X"),
        ({"type": "pie", "x": "region", "y": ["revenue", "orders"]}, "one value"),
    ],
)
def test_bad_chart_edits_say_what_is_wrong(spec, message) -> None:
    with pytest.raises(ChartError, match=message):
        validate_chart(spec, RESULT)


@pytest.mark.parametrize(
    ("type_name", "numeric", "temporal"),
    [
        ("BIGINT", True, False),
        ("DECIMAL(10,2)", True, False),
        ("DOUBLE", True, False),
        ("DATE", False, True),
        ("TIMESTAMP WITH TIME ZONE", False, True),
        ("TIMESTAMP_NS", False, True),
        ("INTERVAL", False, False),  # starts with "INT" but is not a number
        ("INTEGER[]", False, False),  # a list of numbers is not a number
        ("DATE[]", False, False),
        ("VARCHAR", False, False),
        ("BOOLEAN", False, False),
    ],
)
def test_column_types_are_told_apart_exactly(type_name: str, numeric: bool, temporal: bool) -> None:
    assert (is_numeric(type_name), is_temporal(type_name)) == (numeric, temporal)
