"""One chart per analysis: results that stack several separate analyses are split into charts, and
values that cannot share an axis are not drawn on one (no database needed)."""

from app.chat.charts import breakdown_groups, suggest_chart
from app.chat.grounding import fallback_summary

COLUMNS = [
    {"name": "category", "type": "VARCHAR"},
    {"name": "label", "type": "VARCHAR"},
    {"name": "employees", "type": "BIGINT"},
]
GENDER = [["Gender", "F", 120051], ["Gender", "M", 179973]]
BIRTH_YEARS = [["Birth Year", str(year), 20000 + year] for year in range(1952, 1966)]


def test_two_analyses_stacked_in_one_result_get_one_chart_each() -> None:
    chart = suggest_chart(COLUMNS, GENDER + BIRTH_YEARS)

    assert chart is not None
    assert (chart["facet"], chart["x"], chart["y"], chart["series"]) == (
        "category",
        "label",
        ["employees"],
        None,
    )
    assert chart["panels"] == [
        {"value": "Gender", "title": "Employees by gender", "type": "bar"},
        {"value": "Birth Year", "title": "Employees by birth year", "type": "line"},
    ]


def test_the_panels_hold_each_analysis_own_rows_and_nothing_else() -> None:
    rows = GENDER + BIRTH_YEARS
    chart = suggest_chart(COLUMNS, rows)

    (gender, years) = breakdown_groups(COLUMNS, rows, chart or {})

    assert gender[1] == [("F", 120051.0), ("M", 179973.0)]
    assert [label for label, _ in years[1]] == [str(y) for y in range(1952, 1966)]


def test_the_same_labels_under_every_group_is_an_ordinary_grouped_chart_not_a_split() -> None:
    columns = [
        {"name": "department", "type": "VARCHAR"},
        {"name": "gender", "type": "VARCHAR"},
        {"name": "employees", "type": "BIGINT"},
    ]
    rows = [[d, g, 10] for d in ("Sales", "Support", "Finance") for g in ("F", "M")]

    chart = suggest_chart(columns, rows)

    assert chart is not None and "panels" not in chart
    assert chart["type"] == "bar" and chart["series"] is not None  # one series per gender


def test_a_label_repeated_inside_a_group_is_not_a_clean_breakdown() -> None:
    rows = [["A", "x", 1], ["A", "x", 2], ["B", "y", 3], ["B", "z", 4]]

    chart = suggest_chart(COLUMNS, rows)

    assert chart is None or "panels" not in chart


def test_a_group_with_a_single_label_each_is_not_split_into_one_bar_charts() -> None:
    rows = [["Revenue", "total", 100], ["Orders", "count", 20], ["Customers", "count2", 5]]

    chart = suggest_chart(COLUMNS, rows)

    assert chart is None or "panels" not in chart


def test_too_many_separate_analyses_stay_a_table() -> None:
    rows = [[f"Breakdown {i}", f"{i}-{j}", j] for i in range(8) for j in range(3)]

    chart = suggest_chart(COLUMNS, rows)

    assert chart is None or "panels" not in chart


def test_three_analyses_get_three_charts_and_dates_are_a_line() -> None:
    rows = (
        [["Region", r, 5] for r in ("North", "South", "East")]
        + [["Status", s, 7] for s in ("completed", "returned")]
        + [["Month", f"2025-0{m}", 3] for m in (1, 2, 3, 4)]
    )

    chart = suggest_chart(COLUMNS, rows)

    assert chart is not None
    assert [p["type"] for p in chart["panels"]] == ["bar", "bar", "line"]


def test_values_of_very_different_size_get_a_chart_of_their_own_not_one_axis() -> None:
    columns = [
        {"name": "region", "type": "VARCHAR"},
        {"name": "revenue", "type": "DOUBLE"},
        {"name": "orders", "type": "BIGINT"},
    ]
    rows = [["East", 4_500_000.0, 12], ["West", 3_900_000.0, 9], ["North", 2_000_000.0, 7]]

    chart = suggest_chart(columns, rows)

    # the orders would look like zero beside the revenue, and were once dropped without a word:
    # now they have their own chart
    assert chart is not None and chart["y"] == ["revenue"]
    assert [panel["y"] for panel in chart["panels"]] == [["revenue"], ["orders"]]
    assert "omitted" not in chart


def test_values_of_a_similar_size_still_share_a_chart() -> None:
    columns = [
        {"name": "month", "type": "DATE"},
        {"name": "revenue", "type": "DOUBLE"},
        {"name": "cost", "type": "DOUBLE"},
    ]
    rows = [[f"2025-0{m}-01", 100.0 * m, 60.0 * m] for m in (1, 2, 3, 4)]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["y"] == ["revenue", "cost"]


def test_a_single_row_still_shows_every_number() -> None:
    columns = [
        {"name": "revenue", "type": "DOUBLE"},
        {"name": "orders", "type": "BIGINT"},
    ]

    chart = suggest_chart(columns, [[4_500_000.0, 12]])

    assert chart is not None and chart["type"] == "kpi" and chart["y"] == ["revenue", "orders"]


def test_the_written_summary_describes_each_analysis_not_a_made_up_ranking() -> None:
    summary = fallback_summary(COLUMNS, GENDER + BIRTH_YEARS)

    assert summary.startswith("The result holds 2 separate analyses.")
    assert (
        "- **Gender**: M is higher (179,973) than F (120,051), a gap of 59,922, about 49.9% more."
        in summary
    )
    assert (
        "- **Birth Year**: 14 points from 1952 to 1965. It rose from 21,952 to 21,965 (0.1%); "
        "the highest point is 1965 (21,965)." in summary
    )
    assert summary.endswith("has every row.")  # and says where the charts are
    assert "Highest" not in summary.split("\n")[0]  # not "Highest employees: Gender"


def test_a_long_analysis_is_summarised_by_its_biggest_parts() -> None:
    rows = [["Department", f"D{i}", 100 - i] for i in range(8)] + [
        ["Gender", "F", 1],
        ["Gender", "M", 2],
    ]

    summary = fallback_summary(COLUMNS, rows)

    assert "In order: D0 100, D1 99, D2 98, D3 97, D4 96, D5 95 and 2 more." in summary


# ── Combined charts: one bar per group for each period ───────────────────────

YEAR_BY_GENDER = [
    {"name": "birth_year", "type": "INTEGER"},
    {"name": "gender", "type": "VARCHAR"},
    {"name": "employees", "type": "BIGINT"},
]


def test_a_few_years_split_by_gender_are_grouped_bars_one_per_gender_for_each_year() -> None:
    rows = [[year, gender, 1000 + year] for year in range(1952, 1966) for gender in ("F", "M")]

    chart = suggest_chart(YEAR_BY_GENDER, rows)

    assert chart == {
        "type": "bar",
        "x": "birth_year",
        "y": ["employees"],
        "series": "gender",
        "title": "Employees by birth year and gender",
    }


def test_many_periods_are_still_a_trend_a_line_for_each_group() -> None:
    columns = [
        {"name": "month", "type": "DATE"},
        {"name": "gender", "type": "VARCHAR"},
        {"name": "employees", "type": "BIGINT"},
    ]
    rows = [[f"2025-{m:02d}-01", g, m] for m in range(1, 13) for g in ("F", "M")]
    rows += [[f"2026-{m:02d}-01", g, m] for m in range(1, 13) for g in ("F", "M")]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["type"] == "line" and chart["series"] == "gender"


def test_a_category_split_by_another_is_grouped_bars_with_both_named_in_the_title() -> None:
    columns = [
        {"name": "department", "type": "VARCHAR"},
        {"name": "gender", "type": "VARCHAR"},
        {"name": "employees", "type": "BIGINT"},
    ]
    rows = [[d, g, 10] for d in ("Sales", "Support", "Finance") for g in ("F", "M")]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["type"] == "bar"
    assert chart["title"] == "Employees by department and gender"


def test_short_forms_on_a_chart_are_spelled_out() -> None:
    from app.chat.charts import pretty

    assert pretty("cnt") == "Count"
    assert pretty("employee_cnt") == "Employee count"
    assert pretty("avg_amt") == "Average amount"
    assert pretty("revenue") == "Revenue"
    assert pretty("account") == "Account"  # only whole words are changed


def test_asking_for_a_combined_chart_is_recognised_from_the_words() -> None:
    from app.chat.charts import wants_combined

    for question in (
        "analyse by gender and by birth date with combined graph",
        "show both together",
        "put them in one graph",
        "show it in a single chart",
        "side by side please",
        "Combine the two",
    ):
        assert wants_combined(question), question
    for question in (
        "analyse by gender and by birth date show me with graph",
        "how many employees are there",
        "the combination lock code",
    ):
        assert not wants_combined(question), question


# ── Plain words, and a chart only when there is something to draw ────────────

STACKED = [
    {"name": "breakdown", "type": "VARCHAR"},
    {"name": "label", "type": "VARCHAR"},
    {"name": "value", "type": "DOUBLE"},
]
WORKFORCE = [
    ["Average salary", "Overall", 72012.24],
    ["Gender salary", "M", 72044.66],
    ["Gender salary", "F", 71963.57],
    ["Workforce size", "Total", 240124.0],
    *[["Yearly salary", str(1985 + i), 54000.0 + i * 1100] for i in range(5)],
]


def test_an_analysis_with_one_value_is_a_number_not_a_chart_of_one_bar() -> None:
    chart = suggest_chart(STACKED, WORKFORCE)

    assert chart is not None
    assert [(p["value"], p["type"]) for p in chart["panels"]] == [
        ("Average salary", "kpi"),
        ("Gender salary", "bar"),
        ("Workforce size", "kpi"),
        ("Yearly salary", "line"),
    ]


def test_a_chart_is_named_after_what_it_shows_when_the_value_column_says_nothing() -> None:
    chart = suggest_chart(STACKED, WORKFORCE)

    assert chart is not None
    assert [p["title"] for p in chart["panels"]] == [
        "Average salary",
        "Gender salary",
        "Workforce size",
        "Yearly salary",
    ]  # not "Value by gender salary"


def test_each_chart_gets_a_sentence_about_what_it_shows_and_a_number_gets_none() -> None:
    from app.chat.grounding import annotate_panels

    chart = suggest_chart(STACKED, WORKFORCE)
    assert chart is not None
    annotate_panels(STACKED, WORKFORCE, chart)

    notes = {p["value"]: p.get("note") for p in chart["panels"]}
    assert notes["Gender salary"].startswith("M is higher (72,044.66) than F (71,963.57)")
    assert notes["Yearly salary"].startswith("5 points from 1985 to 1989. It rose from 54,000")
    assert notes["Average salary"] is None and notes["Workforce size"] is None


def test_the_summary_reads_a_lone_value_as_a_sentence() -> None:
    summary = fallback_summary(STACKED, WORKFORCE)

    assert "- **Average salary**: The overall average salary is 72,012.24." in summary
    assert "- **Workforce size**: The total workforce size is 240,124." in summary
