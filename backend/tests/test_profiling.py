"""Profiling and join detection on real Parquet files (no database needed)."""

from pathlib import Path

import duckdb
import pytest

from app.engine import duckdb_engine, profiling
from app.engine.duckdb_engine import Column, QueryTimeoutError, TableSource
from app.engine.profiling import JoinTable

ORDERS = (
    "order_id,customer_id,region,amount\n"
    "1,10,Gujarat,120.5\n2,10,Gujarat,80\n3,11,Kerala,40\n4,12,,15\n5,12,Kerala,\n"
)
CUSTOMERS = "id,name,city\n10,Asha,Surat\n11,Ravi,Kochi\n12,Mina,Pune\n13,Omar,Delhi\n"
TAGS = "tag,region\nfast,Gujarat\nslow,Kerala\nfast,Kerala\n"


def make_source(tmp_path: Path, name: str, csv: str) -> TableSource:
    raw = tmp_path / f"{name}.csv"
    raw.write_text(csv, encoding="utf-8")
    target = tmp_path / f"{name}.parquet"
    duckdb_engine.convert_to_parquet(raw, target)
    return TableSource(name, "upload", str(target))


@pytest.fixture
def orders(tmp_path: Path) -> TableSource:
    return make_source(tmp_path, "orders", ORDERS)


def columns_of(source: TableSource) -> list[Column]:
    return duckdb_engine.describe(source)[0]


def test_profile_gives_counts_ranges_and_common_values(orders: TableSource) -> None:
    profile = profiling.profile_table(orders, columns_of(orders), timeout_seconds=30)

    assert profile.row_count == 5
    by_name = {c.name: c for c in profile.columns}
    region = by_name["region"].stats
    assert (region["null_count"], region["null_pct"], region["distinct_count"]) == (1, 20.0, 2)
    assert region["top_values"][0] == {"value": "Gujarat", "count": 2}
    assert (region["min"], region["max"]) == ("Gujarat", "Kerala")
    amount = by_name["amount"].stats
    assert (amount["null_count"], amount["min"], amount["max"]) == (1, "15.0", "120.5")
    assert not amount["searchable"] and by_name["amount"].values is None


def test_only_short_low_cardinality_text_columns_are_searchable(tmp_path: Path) -> None:
    rows = ["code,note"] + [f"C{i},{'x' * 200}" for i in range(3)]
    source = make_source(tmp_path, "codes", "\n".join(rows) + "\n")

    by_name = {
        c.name: c
        for c in profiling.profile_table(source, columns_of(source), timeout_seconds=30).columns
    }

    assert by_name["code"].stats["searchable"] and by_name["code"].values == ["C0", "C1", "C2"]
    assert not by_name["note"].stats["searchable"]  # longer than 127 characters


def test_too_many_distinct_values_are_not_searchable(tmp_path: Path) -> None:
    rows = ["label"] + [f"v{i}" for i in range(profiling.VALUE_INDEX_MAX_DISTINCT + 1)]
    source = make_source(tmp_path, "labels", "\n".join(rows) + "\n")

    column = profiling.profile_table(source, columns_of(source), timeout_seconds=30).columns[0]

    assert column.stats["distinct_count"] == 1025 and not column.stats["searchable"]
    assert column.values is None


def test_distinct_values_returns_every_value_sorted(orders: TableSource) -> None:
    assert profiling.distinct_values(orders, "region", timeout_seconds=30) == ["Gujarat", "Kerala"]


def test_profile_of_an_empty_table(tmp_path: Path) -> None:
    source = make_source(tmp_path, "empty", "a,b\n")

    profile = profiling.profile_table(source, columns_of(source), timeout_seconds=30)

    assert profile.row_count == 0
    assert all(c.stats["null_pct"] == 0.0 for c in profile.columns)


def test_profile_stops_at_the_time_limit(tmp_path: Path) -> None:
    target = tmp_path / "big.parquet"
    with duckdb.connect() as con:
        con.execute(
            "COPY (SELECT i, 'v' || i AS s FROM range(5000000) t(i)) "
            f"TO '{target.as_posix()}' (FORMAT parquet)"
        )
    source = TableSource("big", "upload", str(target))

    with pytest.raises(QueryTimeoutError):
        profiling.profile_table(source, columns_of(source), timeout_seconds=0.05)


def test_foreign_keys_are_detected_with_the_many_side_on_the_left(tmp_path: Path) -> None:
    orders = make_source(tmp_path, "orders", ORDERS)
    customers = make_source(tmp_path, "customers", CUSTOMERS)
    tags = make_source(tmp_path, "tags", TAGS)
    tables = [JoinTable(s.name, columns_of(s)) for s in (customers, orders, tags)]

    found = profiling.detect_joins([orders, customers, tags], tables, timeout_seconds=30)

    assert [(j.left, j.left_column, j.right, j.right_column, j.relationship) for j in found] == [
        ("orders", "customer_id", "customers", "id", "many_to_one")
    ]  # orders.region / tags.region repeat on both sides, so that is not a join key


def test_same_named_unique_keys_are_one_to_one(tmp_path: Path) -> None:
    a = make_source(tmp_path, "a", "k,x\n1,a\n2,b\n3,c\n")
    b = make_source(tmp_path, "b", "k,y\n1,a\n2,b\n3,c\n")
    tables = [JoinTable(s.name, columns_of(s)) for s in (a, b)]

    found = profiling.detect_joins([a, b], tables, timeout_seconds=30)

    assert [(j.left_column, j.relationship) for j in found] == [("k", "one_to_one")]


def test_keys_that_do_not_overlap_are_not_joins(tmp_path: Path) -> None:
    a = make_source(tmp_path, "a", "k\n1\n2\n3\n")
    b = make_source(tmp_path, "b", "k\n7\n8\n9\n")
    tables = [JoinTable(s.name, columns_of(s)) for s in (a, b)]

    assert profiling.detect_joins([a, b], tables, timeout_seconds=30) == []


def test_candidates_need_matching_types_and_names() -> None:
    tables = [
        JoinTable("orders", [Column("customer_id", "BIGINT"), Column("amount", "DOUBLE")]),
        JoinTable("customers", [Column("id", "BIGINT"), Column("amount", "DOUBLE")]),
        JoinTable("stores", [Column("id", "VARCHAR")]),
    ]

    found = profiling.join_candidates(tables)

    assert [(c.left, c.left_column, c.right, c.right_column) for c in found] == [
        ("orders", "customer_id", "customers", "id")
    ]  # DOUBLE is never a key, and a VARCHAR id doesn't match a BIGINT one
