"""One chart per kind of figure, laid out to be read, with nothing dropped silently."""

import pytest

from app.chat.charts import MAX_PANELS, result_roles, suggest_chart
from app.chat.grounding import fallback_summary, ungrounded_figures
from app.chat.measures import analyse

COLUMNS = [
    {"name": "department", "type": "VARCHAR"},
    {"name": "average_salary", "type": "DECIMAL"},
    {"name": "current_employee_count", "type": "BIGINT"},
    {"name": "total_salary_expenditure", "type": "BIGINT"},
]
DEPARTMENTS = [
    ("Sales", 88852.97, 37701),
    ("Marketing", 80058.85, 14842),
    ("Finance", 78559.94, 12437),
    ("Research", 67913.37, 15441),
    ("Production", 67843.3, 53304),
    ("Development", 67657.92, 61386),
    ("Customer Service", 67285.23, 17569),
    ("Quality Management", 65441.99, 14546),
    ("Human Resources", 63921.9, 12898),
]
ROWS = [[name, avg, count, round(avg * count)] for name, avg, count in DEPARTMENTS]
SQL = (
    "SELECT d.name AS department, AVG(s.salary) AS average_salary, "
    "COUNT(*) AS current_employee_count, SUM(s.salary) AS total_salary_expenditure "
    "FROM departments d JOIN salaries s ON s.dept = d.id GROUP BY d.name "
    "ORDER BY average_salary DESC"
)


def measures_drawn(chart: dict) -> list[str]:
    """Every measure a chart draws, in its panels or on its own."""
    return [name for panel in chart.get("panels") or [chart] for name in panel["y"]]


def cols(**types: str) -> list[dict[str, str]]:
    return [{"name": name, "type": type_name} for name, type_name in types.items()]


# ── The case that was wrong: salary, head count and a total on one chart ──────


def test_an_average_a_count_and_a_total_each_get_their_own_chart() -> None:
    chart = suggest_chart(COLUMNS, ROWS, analyse(SQL))

    assert chart is not None
    assert [panel["y"] for panel in chart["panels"]] == [
        ["average_salary"],
        ["current_employee_count"],
        ["total_salary_expenditure"],
    ]
    assert [panel["title"] for panel in chart["panels"]] == [
        "Average salary by department",
        "Current employee count by department",
        "Total salary expenditure by department",
    ]
    assert "omitted" not in chart  # nothing was left out


def test_the_salary_and_the_head_count_never_share_an_axis_even_when_their_sizes_are_close() -> (
    None
):
    # 88K and 61K are within a factor of two of each other: the old size rule drew them together
    chart = suggest_chart(COLUMNS[:3], [row[:3] for row in ROWS], analyse(SQL))

    assert chart is not None and len(chart["panels"]) == 2
    assert all(len(panel["y"]) == 1 for panel in chart["panels"])


def test_the_kinds_are_known_from_the_names_when_there_is_no_sql() -> None:
    chart = suggest_chart(COLUMNS, ROWS)

    assert chart is not None and len(chart["panels"]) == 3


def test_a_figure_that_nothing_identifies_is_not_drawn_against_one_that_is_known() -> None:
    # `employees` is a count to a reader, but nothing here says so; it must not share the axis
    columns = cols(department="VARCHAR", average_salary="DOUBLE", employees="BIGINT")
    rows = [["A", 50000.0, 40000], ["B", 60000.0, 35000]]

    chart = suggest_chart(columns, rows)

    assert chart is not None and [p["y"] for p in chart["panels"]] == [
        ["average_salary"],
        ["employees"],
    ]


def test_two_counts_of_a_similar_size_still_share_a_chart() -> None:
    columns = cols(year="INTEGER", female_count="BIGINT", male_count="BIGINT")
    rows = [[1950 + i, 100 + i, 120 + i] for i in range(5)]

    chart = suggest_chart(columns, rows, analyse("SELECT 1"))

    assert chart is not None and chart["y"] == ["female_count", "male_count"]
    assert "panels" not in chart


def test_two_figures_nothing_identifies_share_a_chart_when_their_sizes_are_alike() -> None:
    columns = cols(month="DATE", revenue="DOUBLE", cost="DOUBLE")
    rows = [[f"2025-0{m}-01", 100.0 * m, 60.0 * m] for m in (1, 2, 3, 4)]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["y"] == ["revenue", "cost"] and "panels" not in chart


def test_sizes_far_apart_split_even_two_figures_of_the_same_kind() -> None:
    columns = cols(region="VARCHAR", revenue="DOUBLE", orders="BIGINT")
    rows = [["East", 4_500_000.0, 12], ["West", 3_900_000.0, 9], ["North", 2_000_000.0, 7]]

    chart = suggest_chart(columns, rows)

    assert chart is not None and [p["y"] for p in chart["panels"]] == [["revenue"], ["orders"]]


# ── Nothing is dropped silently ──────────────────────────────────────────────


@pytest.mark.parametrize("measure_count", [1, 2, 3, 4, 5, 6, 7, 9])
def test_every_measure_is_drawn_or_named_as_left_out(measure_count: int) -> None:
    names = [f"m{i}_{kind}" for i, kind in zip(range(measure_count), "abcdefghi", strict=False)]
    columns = [{"name": "dept", "type": "VARCHAR"}] + [
        {"name": name, "type": "DOUBLE"} for name in names
    ]
    rows = [
        [f"D{r}", *[float(10 ** (i + 1) * (r + 1)) for i in range(measure_count)]] for r in range(4)
    ]

    chart = suggest_chart(columns, rows)

    assert chart is not None
    covered = set(measures_drawn(chart)) | set(chart.get("omitted", []))
    assert covered == set(names)
    assert len(chart.get("panels", [1])) <= MAX_PANELS


def test_more_charts_than_the_limit_name_the_ones_that_were_left_out() -> None:
    names = [f"m{i}" for i in range(8)]
    columns = [{"name": "dept", "type": "VARCHAR"}] + [
        {"name": name, "type": "DOUBLE"} for name in names
    ]
    rows = [[f"D{r}", *[float(1000**i * (r + 1)) for i in range(8)]] for r in range(4)]

    chart = suggest_chart(columns, rows)

    assert chart is not None and len(chart["panels"]) == MAX_PANELS
    assert chart["omitted"] == names[MAX_PANELS:]


def test_a_chart_by_two_groups_gets_a_panel_for_each_measure() -> None:
    columns = cols(
        department="VARCHAR", gender="VARCHAR", average_salary="DOUBLE", employees="BIGINT"
    )
    rows = [
        [d, g, 50000.0 + i, 100 + i]
        for i, (d, g) in enumerate(
            (d, g) for d in ("Sales", "Finance", "Research") for g in ("F", "M")
        )
    ]

    chart = suggest_chart(columns, rows)

    assert chart is not None and chart["series"] == "gender"
    assert [p["y"] for p in chart["panels"]] == [["average_salary"], ["employees"]]


def test_a_trend_of_several_kinds_of_figure_is_a_line_chart_for_each() -> None:
    columns = cols(month="DATE", average_order="DOUBLE", order_count="BIGINT")
    rows = [[f"2025-{m:02d}-01", 80.0 + m, 70 + m] for m in range(1, 7)]

    chart = suggest_chart(columns, rows, analyse("SELECT 1"))

    assert chart is not None and chart["type"] == "line"
    assert [p["type"] for p in chart["panels"]] == ["line", "line"]
    assert "orientation" not in chart  # a time axis stays horizontal, so bars never lie down


# ── Laid out to be read ──────────────────────────────────────────────────────


def test_many_categories_lie_down_and_a_few_short_ones_do_not() -> None:
    nine = suggest_chart(COLUMNS[:2], [row[:2] for row in ROWS])
    few = suggest_chart(
        cols(region="VARCHAR", revenue="DOUBLE"), [["East", 1.0], ["West", 2.0], ["North", 3.0]]
    )

    assert nine is not None and nine["orientation"] == "horizontal"
    assert few is not None and "orientation" not in few


def test_one_long_name_is_enough_to_lie_down() -> None:
    chart = suggest_chart(
        cols(region="VARCHAR", revenue="DOUBLE"),
        [["Customer Service", 1.0], ["Sales", 2.0]],
    )

    assert chart is not None and chart["orientation"] == "horizontal"


def test_bars_are_ranked_unless_the_query_sorted_them_itself() -> None:
    columns, rows = COLUMNS, ROWS

    def sorted_flags(sql: str | None) -> list[bool]:
        chart = suggest_chart(columns, rows, analyse(sql))
        assert chart is not None
        return ["sort" in panel for panel in chart["panels"]]

    unsorted = "SELECT d AS department, AVG(s) AS average_salary FROM t GROUP BY d"
    assert sorted_flags(SQL) == [False, True, True]  # ordered by the first measure: kept as asked
    assert sorted_flags(SQL.replace("ORDER BY average_salary DESC", "")) == [True, True, True]
    assert sorted_flags(SQL.replace("average_salary DESC", "department")) == [False] * 3
    assert sorted_flags(SQL.replace("average_salary DESC", "average_salary ASC")) == [
        False,
        True,
        True,
    ]
    assert sorted_flags(None) == [False] * 3  # no SQL: nothing is known, so nothing is reordered
    assert unsorted  # (kept for the reader: the form of query this rule is about)


def test_an_ascending_request_is_never_turned_around() -> None:
    chart = suggest_chart(COLUMNS, ROWS, analyse(SQL.replace("DESC", "ASC")))

    assert chart is not None and "sort" not in chart["panels"][0]  # the query's own order stays


def test_a_chart_split_by_a_series_is_not_ranked() -> None:
    columns = cols(department="VARCHAR", gender="VARCHAR", employees="BIGINT")
    rows = [[d, g, 10 + i] for i, (d, g) in enumerate((d, g) for d in "ABCDEF" for g in "FM")]

    chart = suggest_chart(
        columns,
        rows,
        analyse("SELECT department, gender, COUNT(*) AS employees FROM t GROUP BY 1, 2"),
    )

    assert chart is not None and chart["series"] == "gender" and "sort" not in chart


# ── The written summary covers every figure ──────────────────────────────────


def test_the_summary_names_every_measure_and_who_leads_on_what() -> None:
    summary = fallback_summary(COLUMNS, ROWS, False, analyse(SQL))

    assert summary.splitlines()[0] == "9 rows, compared on 3 measures:"
    assert "**Average salary**: highest Sales (88,852.97), lowest Human Resources" in summary
    assert (
        "**Current employee count**: highest Development (61,386), lowest Finance (12,437)"
        in summary
    )
    assert "**Total salary expenditure**: highest Development" in summary
    assert summary.splitlines()[-1] == (
        "Sales leads on average salary; Development leads on current employee count "
        "and total salary expenditure."
    )


def test_the_summary_states_the_overall_figures_it_was_given_and_only_those() -> None:
    overall = {
        "average_salary": 72012.03,
        "current_employee_count": 240124.0,
        "total_salary_expenditure": 17291234567.0,
    }

    summary = fallback_summary(COLUMNS, ROWS, False, analyse(SQL), overall)

    assert "overall average 72,012.03" in summary
    assert "total 240,124" in summary and "total 17,291,234,567" in summary
    without = fallback_summary(COLUMNS, ROWS, False, analyse(SQL))
    assert "overall" not in without and "total 2" not in without  # never made up from the rows


def test_every_number_in_the_summary_is_in_the_result() -> None:
    from app.chat.grounding import allowed_numbers

    summary = fallback_summary(COLUMNS, ROWS, False, analyse(SQL))

    assert ungrounded_figures(summary, allowed_numbers("", COLUMNS, ROWS, ROWS)) == []


def test_one_leader_on_everything_is_said_once() -> None:
    columns = cols(team="VARCHAR", wins="BIGINT", games="BIGINT")
    rows = [["Reds", 30, 40], ["Blues", 20, 35], ["Greens", 10, 30]]

    summary = fallback_summary(columns, rows)

    assert summary.splitlines()[-1] == "Reds leads on every measure."


def test_a_tie_is_called_a_tie_and_gives_nobody_the_lead() -> None:
    columns = cols(team="VARCHAR", wins="BIGINT", games="BIGINT")
    rows = [["Reds", 30, 40], ["Blues", 30, 35], ["Greens", 10, 30]]

    summary = fallback_summary(columns, rows)

    assert "highest Reds (30, tied)" in summary
    assert "Reds leads on games" in summary and "wins" not in summary.splitlines()[-1]


def test_a_measure_that_is_the_same_in_every_row_has_no_highest_or_lowest() -> None:
    columns = cols(team="VARCHAR", wins="BIGINT", games="BIGINT")
    rows = [["Reds", 5, 40], ["Blues", 5, 35]]

    summary = fallback_summary(columns, rows)

    assert "**Wins**: 5 in every row." in summary


def test_the_roles_exclude_a_year_and_an_id_from_the_measures() -> None:
    columns = cols(year="INTEGER", customer_id="BIGINT", gender="VARCHAR", orders="BIGINT")

    roles = result_roles(columns, [[1950, 1, "F", 3], [1951, 2, "M", 4]])

    assert roles["measure"] == ["orders"] and roles["time"] == ["year"]
