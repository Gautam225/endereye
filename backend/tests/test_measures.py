"""What the SQL says about a result's columns: their kinds, the order, and the overall figures."""

import duckdb
import pytest

from app.chat.measures import Shape, analyse, kind_from_name

DEPARTMENTS = """
SELECT d.dept_name AS department,
       ROUND(AVG(s.salary), 2) AS average_salary,
       COUNT(DISTINCT s.emp_no) AS current_employees,
       CAST(SUM(s.salary) AS BIGINT) AS total_salary_expenditure
FROM departments d JOIN salaries s ON s.dept_no = d.dept_no
WHERE s.to_date = '9999-01-01'
GROUP BY d.dept_name
ORDER BY average_salary DESC
"""


def test_each_column_is_what_the_select_says_whatever_it_is_named() -> None:
    shape = analyse(DEPARTMENTS, "postgresql")

    assert shape.known
    assert shape.kinds == {
        "average_salary": "avg",
        "current_employees": "count",
        "total_salary_expenditure": "sum",
    }
    assert shape.kind_of("Average_Salary") == "avg"  # case does not matter


def test_a_misleading_name_does_not_fool_it() -> None:
    shape = analyse("SELECT region, AVG(amount) AS total, COUNT(*) AS average FROM t GROUP BY 1")

    assert shape.kinds == {"total": "avg", "average": "count"}


def test_arithmetic_on_aggregates_is_a_ratio_or_other_never_a_sum() -> None:
    shape = analyse(
        "SELECT region, SUM(a) / COUNT(*) AS per_order, SUM(a) - SUM(b) AS net FROM t GROUP BY 1"
    )

    assert shape.kinds == {"per_order": "ratio", "net": "other"}


def test_columns_passed_through_a_cte_keep_the_kind_they_were_given() -> None:
    star = analyse(
        "WITH s AS (SELECT region, AVG(amount) AS avg_amount, COUNT(*) AS n FROM sales "
        "GROUP BY region) SELECT * FROM s ORDER BY avg_amount DESC"
    )
    renamed = analyse(
        "WITH s AS (SELECT region, AVG(amount) AS avg_amount, COUNT(*) AS n FROM sales "
        "GROUP BY region) SELECT region, avg_amount AS typical, n FROM s"
    )

    assert star.kinds == {"avg_amount": "avg", "n": "count"}
    assert star.order_by == "avg_amount"
    assert renamed.kinds == {"typical": "avg", "n": "count"}


@pytest.mark.parametrize(
    ("sql", "ordered", "key"),
    [
        ("SELECT r, SUM(a) AS revenue FROM t GROUP BY r", False, None),
        ("SELECT r, SUM(a) AS revenue FROM t GROUP BY r ORDER BY revenue DESC", True, "revenue"),
        ("SELECT r, SUM(a) AS revenue FROM t GROUP BY r ORDER BY 2", True, "revenue"),
        ("SELECT r, SUM(a) AS revenue FROM t GROUP BY r ORDER BY SUM(a)", True, "revenue"),
        ("SELECT r, SUM(a) AS revenue FROM t GROUP BY r ORDER BY r", True, "r"),
        ("SELECT r, SUM(a) AS revenue FROM t GROUP BY r ORDER BY length(r)", True, None),
    ],
)
def test_the_first_sort_key_is_found_whichever_way_it_is_written(
    sql: str, ordered: bool, key: str | None
) -> None:
    shape = analyse(sql)

    assert (shape.ordered, shape.order_by) == (ordered, key)


def test_the_overall_figures_are_exact_not_an_average_of_averages() -> None:
    db = duckdb.connect()
    db.execute(
        "CREATE TABLE pay AS SELECT * FROM (VALUES ('A', 1, 100), ('B', 2, 10), ('B', 3, 10), "
        "('B', 4, 10)) t(dept, emp, salary)"
    )
    sql = (
        "SELECT dept, AVG(salary) AS avg_salary, COUNT(DISTINCT emp) AS people, "
        "SUM(salary) AS total FROM pay GROUP BY dept ORDER BY dept"
    )
    shape = analyse(sql, "duckdb")

    grouped = db.execute(sql).fetchall()
    overall = db.execute(shape.totals_sql or "").fetchall()

    assert shape.totals_names == ("avg_salary", "people", "total")
    assert overall == [(32.5, 4, 130)]
    # what adding up or averaging the rows would have said: wrong
    assert sum(r[1] for r in grouped) / len(grouped) == 55
    assert sum(r[2] for r in grouped) == 4


def test_a_distinct_count_is_not_the_sum_of_its_groups() -> None:
    db = duckdb.connect()
    db.execute(
        "CREATE TABLE seen AS SELECT * FROM (VALUES ('X', 1), ('X', 2), ('Y', 2), ('Y', 3)) "
        "t(team, person)"
    )
    sql = "SELECT team, COUNT(DISTINCT person) AS people, COUNT(*) AS rows FROM seen GROUP BY team"
    shape = analyse(sql, "duckdb")

    assert db.execute(shape.totals_sql or "").fetchall() == [(3, 4)]  # 3 people, not 2 + 2


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT r, SUM(a) AS revenue FROM t GROUP BY r",
        "SELECT r, SUM(a) AS revenue FROM t GROUP BY 1",
        "SELECT r, SUM(a) AS revenue FROM t GROUP BY ALL",
        "SELECT date_trunc('month', d) AS m, SUM(a) AS revenue FROM t GROUP BY m ORDER BY m",
        "SELECT r, COUNT(*) FILTER (WHERE a > 5) AS big, SUM(a) AS revenue FROM t GROUP BY r",
        "SELECT r, SUM(a) AS revenue FROM t GROUP BY r ORDER BY revenue DESC LIMIT 5",
    ],
)
def test_the_overall_query_is_the_same_query_without_its_grouping(sql: str) -> None:
    shape = analyse(sql, "duckdb")

    assert shape.totals_sql is not None
    assert "GROUP BY" not in shape.totals_sql and "ORDER BY" not in shape.totals_sql
    assert "LIMIT" not in shape.totals_sql
    assert "FROM t" in shape.totals_sql


def test_a_limit_is_recorded_so_the_caller_can_tell_whether_it_cut_groups_off() -> None:
    shape = analyse("SELECT r, SUM(a) AS x FROM t GROUP BY r ORDER BY x DESC LIMIT 5", "duckdb")

    assert shape.limit == 5 and shape.totals_sql is not None
    assert analyse("SELECT r, SUM(a) AS x FROM t GROUP BY r", "duckdb").limit is None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT r, SUM(a) AS x FROM t GROUP BY r HAVING SUM(a) > 5",  # picks some groups
        "SELECT r, SUM(a) AS x FROM t GROUP BY r LIMIT 5 OFFSET 5",  # skips groups
        "SELECT r, SUM(a) AS x FROM t GROUP BY r LIMIT n",  # not a number
        "SELECT r, SUM(a) AS x, SUM(SUM(a)) OVER () AS grand FROM t GROUP BY r",  # window
        "SELECT r, (SELECT COUNT(*) FROM u WHERE u.r = t.r) AS c, SUM(a) AS x FROM t GROUP BY r",
        "SELECT r, SUM(a) AS x FROM t GROUP BY ROLLUP (r)",
        "SELECT DISTINCT r, SUM(a) AS x FROM t GROUP BY r",
        "SELECT r, AVG(a) FROM t GROUP BY r",  # no alias to name the column by
        "SELECT r, a FROM t ORDER BY a",  # nothing grouped
        "SELECT r, upper(r) AS shout, SUM(a) AS x FROM t GROUP BY r",  # not a group key
        "SELECT a FROM t UNION SELECT b FROM u",
        "SELEC nonsense (",
        "",
    ],
)
def test_no_overall_query_when_it_could_not_be_exact(sql: str) -> None:
    assert analyse(sql, "duckdb").totals_sql is None


def test_unreadable_sql_is_unknown_and_the_names_are_used_instead() -> None:
    shape = analyse("SELEC nonsense (")

    assert shape == Shape()
    assert shape.kind_of("average_salary") == "avg" and shape.kind_of("revenue") is None
    assert analyse(None) == Shape() and analyse("") == Shape()


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("average_salary", "avg"),
        ("avg_salary", "avg"),
        ("mean_age", "avg"),
        ("current_employee_count", "count"),
        ("headCount", "count"),
        ("number_of_orders", "count"),
        ("total_count", "count"),  # count wins over total
        ("total_salary_expenditure", "sum"),
        ("pct_female", "ratio"),
        ("max_salary", "max"),
        ("min_salary", "min"),
        ("employees", None),
        ("revenue", None),
    ],
)
def test_the_kind_guessed_from_a_name(name: str, kind: str | None) -> None:
    assert kind_from_name(name) == kind
