import datetime as dt
import decimal
from pathlib import Path

import duckdb
import pytest

from app.core.errors import AppError
from app.engine.duckdb_engine import (
    QueryFailedError,
    QueryTimeoutError,
    TableSource,
    convert_to_parquet,
    describe,
    run_query,
    to_json_value,
)


@pytest.fixture
def sales(tmp_path: Path) -> TableSource:
    raw = tmp_path / "sales.csv"
    raw.write_text(
        "region,amount,sold_on\nGJ,120.5,2026-01-05\nMH,80,2026-01-06\nGJ,40,2026-02-01\n"
    )
    target = tmp_path / "sales.parquet"
    convert_to_parquet(raw, target)
    return TableSource("sales", "upload", str(target))


def test_csv_upload_becomes_a_queryable_table(sales: TableSource) -> None:
    columns, rows = describe(sales)
    assert [(c.name, c.type) for c in columns] == [
        ("region", "VARCHAR"),
        ("amount", "DOUBLE"),
        ("sold_on", "DATE"),
    ]
    assert rows == 3

    result = run_query(
        [sales],
        "SELECT region, sum(amount) AS total FROM sales GROUP BY region ORDER BY region",
        max_rows=100,
        timeout_seconds=10,
    )
    assert result.rows == [["GJ", 160.5], ["MH", 80.0]]
    assert [c.name for c in result.columns] == ["region", "total"]
    assert result.truncated is False


@pytest.mark.parametrize(
    ("name", "make"),
    [
        ("data.json", "COPY (SELECT 1 AS id, 'a' AS label) TO '{path}' (FORMAT json, ARRAY true)"),
        ("data.jsonl", "COPY (SELECT 1 AS id, 'a' AS label) TO '{path}' (FORMAT json)"),
        ("data.parquet", "COPY (SELECT 1 AS id, 'a' AS label) TO '{path}' (FORMAT parquet)"),
        ("data.xlsx", "COPY (SELECT 1 AS id, 'a' AS label) TO '{path}' (FORMAT xlsx, HEADER true)"),
    ],
)
def test_other_file_formats_are_converted(tmp_path: Path, name: str, make: str) -> None:
    source = tmp_path / name
    with duckdb.connect() as con:
        if name.endswith(".xlsx"):
            con.execute("LOAD excel")
        con.execute(make.format(path=source.as_posix()))
    target = tmp_path / "out.parquet"

    convert_to_parquet(source, target)

    columns, rows = describe(TableSource("t", "upload", str(target)))
    assert [c.name for c in columns] == ["id", "label"]
    assert rows == 1


def test_an_unreadable_file_gives_a_clear_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.parquet"
    broken.write_text("this is not parquet")
    with pytest.raises(AppError, match="Could not read this file as Parquet"):
        convert_to_parquet(broken, tmp_path / "out.parquet")
    assert not (tmp_path / "out.parquet").exists()


def test_results_are_cut_at_the_row_limit(sales: TableSource) -> None:
    result = run_query([sales], "SELECT * FROM sales", max_rows=2, timeout_seconds=10)
    assert len(result.rows) == 2
    assert result.truncated is True


def test_slow_queries_are_stopped(sales: TableSource) -> None:
    with pytest.raises(QueryTimeoutError, match=r"longer than 0\.3 seconds"):
        run_query(
            [sales],
            "SELECT count(*) FROM range(10000000000) a, range(100) b",
            max_rows=10,
            timeout_seconds=0.3,
        )


def test_sql_errors_are_explained(sales: TableSource) -> None:
    with pytest.raises(QueryFailedError, match="The query failed"):
        run_query([sales], "SELECT no_such_column FROM sales", max_rows=10, timeout_seconds=10)


def test_other_files_stay_unreadable_even_if_the_guard_were_bypassed(
    sales: TableSource, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.csv"
    secret.write_text("password\nhunter2\n")
    for sql in (
        f"SELECT * FROM read_csv('{secret.as_posix()}')",
        "SET enable_external_access = true",
    ):
        with pytest.raises(QueryFailedError):
            run_query([sales], sql, max_rows=10, timeout_seconds=10)


def test_delta_tables_are_read_from_their_folder(tmp_path: Path) -> None:
    deltalake = pytest.importorskip("deltalake")
    pa = pytest.importorskip("pyarrow")
    folder = tmp_path / "orders_delta"
    deltalake.write_deltalake(str(folder), pa.table({"id": [1, 2, 3], "city": ["A", "B", "A"]}))

    source = TableSource("orders", "delta_path", str(folder))
    columns, rows = describe(source)
    assert ([c.name for c in columns], rows) == (["id", "city"], 3)
    result = run_query(
        [source],
        "SELECT city, count(*) FROM orders GROUP BY 1 ORDER BY 1",
        max_rows=10,
        timeout_seconds=10,
    )
    assert result.rows == [["A", 2], ["B", 1]]


def test_values_are_made_safe_for_json_and_javascript() -> None:
    assert to_json_value(dt.date(2026, 1, 5)) == "2026-01-05"
    assert to_json_value(decimal.Decimal("12.50")) == 12.5
    assert to_json_value(2**60) == str(2**60)  # too big for a JavaScript number
    assert to_json_value(float("nan")) is None
    assert to_json_value(b"\x00\x01") == "AAE="
    assert to_json_value([dt.time(9, 30), {"k": decimal.Decimal("1")}]) == ["09:30:00", {"k": 1.0}]
