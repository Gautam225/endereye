import re

import pytest

from app.engine.sql_guard import SqlNotAllowedError, check_query

TABLES = {"orders", "customers"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        "select city, count(*) from orders group by city order by 2 desc;",
        "WITH big AS (SELECT * FROM orders WHERE total > 100) SELECT * FROM big",
        "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id",
        "SELECT * FROM ORDERS",  # names are not case-sensitive
        "SELECT * FROM range(10)",
        "SELECT 1 + 1 AS two",
        "SELECT * FROM orders UNION ALL SELECT * FROM orders",
    ],
)
def test_read_only_queries_on_space_tables_are_allowed(sql: str) -> None:
    assert check_query(sql, TABLES) == sql.strip().rstrip(";")


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("", "Write a query first"),
        ("SELECT 1; SELECT 2", "one query at a time"),
        ("DELETE FROM orders", "Only SELECT queries"),
        ("DROP TABLE orders", "Only SELECT queries"),
        ("INSERT INTO orders VALUES (1)", "Only SELECT queries"),
        ("COPY orders TO 'out.csv'", "Only SELECT queries"),
        ("ATTACH 'other.db'", "Only SELECT queries"),
        ("PRAGMA version", "Only SELECT queries"),
        ("SET enable_external_access = true", "Only SELECT queries"),
        ("SELECT * FROM read_csv('C:/secret.csv')", "read_csv() is not allowed"),
        ("SELECT * FROM delta_scan('C:/data')", "delta_scan() is not allowed"),
        ("SELECT * FROM glob('*')", "glob() is not allowed"),
        ("SELECT * FROM duckdb_settings()", "duckdb_settings() is not allowed"),
        ("SELECT getenv('PATH')", "getenv() is not allowed"),
        ("SELECT * FROM payroll", "no table called 'payroll'"),
        ("SELECT * FROM information_schema.tables", "names on their own"),
        ("SELECT * FROM 'C:/secret.parquet'", "no table called"),
        ("SELEC * FRM orders", "Check the spelling"),
        ("SELECT * FROM", "could not be read"),
    ],
)
def test_everything_else_is_refused_with_a_reason(sql: str, reason: str) -> None:
    with pytest.raises(SqlNotAllowedError, match=re.escape(reason)):
        check_query(sql, TABLES)
