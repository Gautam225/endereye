"""Asking questions of an external PostgreSQL database, start to finish (needs the test server).

The assistant is scripted (no AI service is called), but everything after it is real: the SQL
guard, the read-only login check, the read-only transaction, the timeouts, and the rows that come
back from the database.
"""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_benchmarks import add_item, run_all
from test_chat import FakeLLM, ask, conversation, events, final, rewrite, sql_plan, use
from test_connections import ExternalServer, build_client, conn_api, create, server  # noqa: F401
from test_external_tables import admin_sql, attach, objects, ready  # noqa: F401
from test_spaces import Person, admin, code, data_dir, new_space, person  # noqa: F401

from app.core.config import Settings

pytestmark = pytest.mark.db

DATA = [
    "DELETE FROM public.orders",
    "DELETE FROM public.customers",
    "INSERT INTO public.customers VALUES (1, 'Asha', 'asha@x.com'), (2, 'Ravi', 'ravi@x.com'), "
    "(3, 'Mina', 'mina@x.com')",
    "INSERT INTO public.orders (id, amount, customer_id) VALUES "
    "(1, 10, 1), (2, 20, 1), (3, 30, 2), (4, 40, 3), (5, 50, 3)",
]

REVENUE = (
    "SELECT c.name AS customer, sum(o.amount) AS revenue FROM orders o "
    "JOIN customers c ON c.id = o.customer_id GROUP BY c.name ORDER BY revenue DESC, c.name"
)
EXPECTED = [["Mina", 90], ["Asha", 30], ["Ravi", 30]]


@pytest.fixture(scope="module", autouse=True)
def data(settings: Settings, objects: None) -> None:
    admin_sql(settings, *DATA)


def warehouse(
    boss: Person, server: ExternalServer, *tables: str, **connection: Any
) -> tuple[str, str]:
    """A space on the external database with these tables. Returns (space id, connection id)."""
    cid = ready(boss, server, **connection)
    space_id = new_space(boss, "Warehouse")
    response = attach(boss, space_id, cid, *(tables or ("public.orders", "public.customers")))
    assert response.status_code == 201, response.text
    return space_id, cid


def database_rows(settings: Settings, sql: str) -> list[list[Any]]:
    """The same question asked straight to the database, to compare with what the app shows."""
    import asyncio

    import asyncpg

    url = settings.sqlalchemy_url

    async def run() -> list[list[Any]]:
        conn = await asyncpg.connect(
            host=url.host, port=url.port, user=url.username, password=url.password,
            database="eoe_external_test",
        )  # fmt: skip
        try:
            return [list(r.values()) for r in await conn.fetch(sql)]
        finally:
            await conn.close()

    return asyncio.run(run())


def ask_sql(boss: Person, space_id: str, llm: FakeLLM, api: TestClient, question: str = "q") -> Any:
    use(api, llm)
    return final(events(ask(boss, space_id, conversation(boss, space_id), question)))


# ── A question, start to finish ──────────────────────────────────────────────


def test_a_question_is_answered_with_the_real_rows_of_the_database(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    llm = FakeLLM(chat_sql=[sql_plan(REVENUE)])

    message = ask_sql(boss, space_id, llm, conn_api, "Total revenue by customer?")

    assert message["status"] == "ok" and message["attempts"] == 1
    assert message["sql"] == REVENUE  # the person sees their own table names
    assert [c["name"] for c in message["columns"]] == ["customer", "revenue"]
    assert [c["type"] for c in message["columns"]] == ["VARCHAR", "DECIMAL"]
    assert message["rows"] == EXPECTED and message["row_count"] == 3
    expected_in_database = database_rows(
        settings,
        "SELECT c.name, sum(o.amount)::float8 FROM orders o "
        "JOIN customers c ON c.id = o.customer_id "
        "GROUP BY c.name ORDER BY 2 DESC, 1",
    )
    assert message["rows"] == expected_in_database  # what the app shows is what the database says
    assert message["chart"]["type"] == "bar"
    assert message["trusted"] is False


def test_a_comparison_of_several_figures_is_charted_one_each_with_the_databases_overall_figures(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    compare = (
        "SELECT c.name AS customer, AVG(o.amount) AS average_order, COUNT(*) AS order_count, "
        "SUM(o.amount) AS total_amount FROM orders o JOIN customers c ON c.id = o.customer_id "
        "GROUP BY c.name ORDER BY average_order DESC"
    )
    llm = FakeLLM(chat_sql=[sql_plan(compare)])

    message = ask_sql(boss, space_id, llm, conn_api, "Compare the customers")

    assert message["status"] == "ok" and message["attempts"] == 1
    chart = message["chart"]
    assert [panel["y"] for panel in chart["panels"]] == [
        ["average_order"],
        ["order_count"],
        ["total_amount"],
    ]
    overall = database_rows(
        settings,
        "SELECT AVG(o.amount)::float8, COUNT(*)::float8, SUM(o.amount)::float8 "
        "FROM orders o JOIN customers c ON c.id = o.customer_id",
    )[0]
    assert [tile["value"] for tile in chart["totals"]] == pytest.approx(overall)
    # This connection keeps its rows from the AI service, so the summary is written here and
    # says what each figure shows, with the overall figures that the database worked out.
    assert llm.purposes() == ["chat_sql"]
    assert message["answer"].startswith("3 rows, compared on 3 measures:")
    assert "overall average 30" in message["answer"] and "total 150" in message["answer"]


def table_ids(boss: Person, space_id: str) -> dict[str, str]:
    return {t["name"]: t["id"] for t in boss.get(f"/spaces/{space_id}/tables").json()}


def add_rule(boss: Person, space_id: str, table: str, **body: Any) -> Any:
    response = boss.post(
        f"/spaces/{space_id}/access-rules",
        json={"table_id": table_ids(boss, space_id)[table], "audience": "everyone", **body},
    )
    assert response.status_code == 201, response.text
    return response


def test_a_row_filter_holds_for_every_query_on_the_external_database(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    add_rule(boss, space_id, "orders", kind="row_filter", expression="amount >= 30")
    totals = "SELECT count(*) AS n, sum(amount) AS total FROM orders"
    joined = (
        "SELECT c.name AS customer, sum(o.amount) AS revenue FROM orders o "
        "JOIN customers c ON c.id = o.customer_id GROUP BY c.name ORDER BY c.name"
    )
    in_cte = "WITH o AS (SELECT * FROM orders) SELECT count(*) AS n FROM o"

    one = ask_sql(boss, space_id, FakeLLM(chat_sql=[sql_plan(totals)]), conn_api)
    two = ask_sql(boss, space_id, FakeLLM(chat_sql=[sql_plan(joined)]), conn_api)
    three = ask_sql(boss, space_id, FakeLLM(chat_sql=[sql_plan(in_cte)]), conn_api)

    assert one["rows"] == [[3, 120]]  # the orders of 30, 40 and 50, and no others
    assert two["rows"] == [["Mina", 90], ["Ravi", 30]]
    assert three["rows"] == [[3]]


def test_a_masked_column_reads_empty_and_a_hidden_one_is_not_there_on_the_external_database(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    add_rule(boss, space_id, "customers", kind="mask_column", column="email")
    emails = "SELECT name, email FROM customers ORDER BY name"

    masked = ask_sql(boss, space_id, FakeLLM(chat_sql=[sql_plan(emails)]), conn_api)

    assert masked["rows"] == [["Asha", None], ["Mina", None], ["Ravi", None]]
    add_rule(boss, space_id, "customers", kind="hide_column", column="name")
    llm = FakeLLM(
        chat_sql=[sql_plan("SELECT name FROM customers")],
        chat_repair=[sql_plan("SELECT id FROM customers ORDER BY id")],
    )
    hidden = ask_sql(boss, space_id, llm, conn_api)

    assert hidden["attempts"] == 2 and hidden["rows"] == [[1], [2], [3]]
    (repair,) = llm.prompts("chat_repair")
    assert "name" in repair  # the guard said the column could not be used
    (first,) = llm.prompts("chat_sql")
    assert "- name " not in first and "- id " in first  # the assistant was never told about it


def test_a_row_filter_that_does_not_fit_the_external_table_is_refused(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)

    response = boss.post(
        f"/spaces/{space_id}/access-rules",
        json={
            "table_id": table_ids(boss, space_id)["orders"],
            "kind": "row_filter",
            "expression": "amount = 'many'",
            "audience": "everyone",
        },
    )

    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_rule"


def test_the_assistant_is_told_to_write_postgresql_and_given_the_confirmed_joins_and_rules(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={
            "kind": "instruction",
            "title": "",
            "body": "Revenue means the sum of order amounts.",
        },
    )
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={
            "kind": "glossary",
            "title": "VIP",
            "body": "A customer with more than 50 in orders.",
        },
    )
    llm = FakeLLM(chat_sql=[sql_plan(REVENUE)])

    ask_sql(boss, space_id, llm, conn_api, "revenue by customer for our VIP customers")

    (prompt,) = llm.prompts("chat_sql")
    assert "PostgreSQL" in prompt and "DuckDB" not in prompt
    assert "orders.customer_id = customers.id" in prompt  # the foreign key, as a confirmed join
    assert "Revenue means the sum of order amounts." in prompt
    assert "A customer with more than 50 in orders." in prompt  # the glossary term


def test_a_saved_example_runs_on_the_database_and_guides_the_next_question(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)

    saved = boss.post(
        f"/spaces/{space_id}/knowledge",
        json={
            "kind": "example_sql",
            "title": "What is the revenue by customer?",
            "body": REVENUE,
            "trusted": True,
        },
    )

    assert saved.status_code == 201, saved.text
    llm = FakeLLM(chat_sql=[sql_plan(REVENUE)])
    message = ask_sql(boss, space_id, llm, conn_api, "What is the revenue by customer?")
    assert message["trusted"] is True  # same SQL as a trusted example
    assert "Example queries" in llm.prompts("chat_sql")[0]


def test_an_example_or_definition_that_does_not_work_on_the_database_is_refused(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)

    def example(body: str) -> Any:
        return boss.post(
            f"/spaces/{space_id}/knowledge",
            json={"kind": "example_sql", "title": "x question", "body": body},
        )

    unknown_column = example("SELECT revenue FROM orders")
    runtime_error = example("SELECT amount / 0 FROM orders")
    write = example("DELETE FROM orders")
    assert unknown_column.status_code == 400 and "revenue" in unknown_column.text
    assert runtime_error.status_code == 400 and "does not run" in runtime_error.text
    assert write.status_code == 400

    def expression(**changes: Any) -> Any:
        return boss.post(
            f"/spaces/{space_id}/expressions",
            json={
                "name": "Revenue",
                "type": "measure",
                "expression": "sum(amount)",
                "table_name": "orders",
                **changes,
            },
        )

    assert expression().status_code == 201
    broken = expression(name="Broken", expression="sum(nope)")
    assert (broken.status_code, code(broken)) == (400, "invalid_expression")
    unsafe = expression(name="Unsafe", expression="pg_sleep(5)")
    assert (unsafe.status_code, code(unsafe)) == (400, "invalid_expression")


# ── Mistakes are corrected without touching the data ─────────────────────────


def test_a_wrong_column_is_caught_before_the_database_and_corrected(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    llm = FakeLLM(
        chat_sql=[sql_plan("SELECT revenue FROM orders")],
        chat_repair=[sql_plan("SELECT sum(amount) AS revenue FROM orders")],
    )

    message = ask_sql(boss, space_id, llm, conn_api)

    assert (message["status"], message["attempts"]) == ("ok", 2)
    assert message["rows"] == [[150]]
    (repair,) = llm.prompts("chat_repair")
    assert "revenue" in repair and "orders(" in repair  # told which columns exist


def test_an_error_from_the_database_is_corrected_too(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    llm = FakeLLM(
        chat_sql=[sql_plan("SELECT sum(amount) / 0 AS ratio FROM orders")],
        chat_repair=[sql_plan("SELECT sum(amount) / count(*) AS ratio FROM orders")],
    )

    message = ask_sql(boss, space_id, llm, conn_api)

    assert (message["status"], message["attempts"]) == ("ok", 2)
    assert "division by zero" in llm.prompts("chat_repair")[0]


# ── Nothing can change the data ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET amount = 0",
        "DROP TABLE orders",
        "INSERT INTO orders (id, amount) VALUES (99, 1)",
        "SELECT pg_sleep(30)",
        "SELECT set_config('default_transaction_read_only', 'off', false)",
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT 1; DELETE FROM orders",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    ],
)
def test_the_assistant_cannot_change_or_probe_the_database_whatever_it_writes(
    conn_api: TestClient, server: ExternalServer, settings: Settings, sql: str
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    llm = FakeLLM(chat_sql=[sql_plan(sql)], chat_repair=[sql_plan(sql)])

    message = ask_sql(boss, space_id, llm, conn_api)

    assert message["status"] == "failed" and message["rows"] is None
    assert database_rows(settings, "SELECT count(*) FROM public.orders") == [[5]]  # untouched


def test_a_write_cannot_get_through_the_edit_and_run_route_either(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)

    for sql in ("DELETE FROM orders", "SELECT 1; DROP TABLE orders", "SELECT * FROM pg_user"):
        response = boss.post(f"/spaces/{space_id}/query", json={"sql": sql})
        assert response.status_code == 400, sql
    assert database_rows(settings, "SELECT count(*) FROM public.orders") == [[5]]


def test_even_if_the_guard_were_bypassed_the_database_session_is_read_only(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    """The second wall: run SQL the guard would refuse, straight on a session opened the way the
    app opens one, and see the database itself refuse it."""
    import asyncio

    from app.engine import postgres_connect, postgres_engine

    async def attempt() -> str:
        conn = await postgres_connect.open_connection(
            postgres_connect.Credentials(
                server.host,
                server.port,
                server.database,
                "eoe_writer_t",  # a login that *could* insert into orders
                server.passwords["eoe_writer_t"],
                "disable",
            ),
            connect_timeout=5,
            statement_timeout_seconds=5,
        )
        try:
            async with conn.transaction(readonly=True):
                try:
                    await postgres_engine.run_query(
                        conn,
                        "INSERT INTO public.orders (id, amount) VALUES (99, 1)",
                        max_rows=10,
                        timeout_seconds=5,
                    )
                except Exception as exc:
                    return str(exc)
                return "no error"
        finally:
            await conn.close()

    assert "read-only" in asyncio.run(attempt())
    assert database_rows(settings, "SELECT count(*) FROM public.orders") == [[5]]


# ── Columns an admin hid stay hidden ─────────────────────────────────────────


def test_a_hidden_column_is_not_shown_to_the_assistant_and_cannot_be_read(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    meta = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/metadata").json()}
    email = next(c for c in meta["customers"]["columns"] if c["name"] == "email")
    hidden = boss.patch(
        f"/spaces/{space_id}/tables/{meta['customers']['id']}/columns/{email['id']}",
        json={"hidden": True},
    )
    assert hidden.status_code == 200

    llm = FakeLLM(
        chat_sql=[sql_plan("SELECT email FROM customers")],
        chat_repair=[sql_plan("SELECT * FROM customers ORDER BY id")],
    )
    message = ask_sql(boss, space_id, llm, conn_api)

    assert "- email " not in llm.prompts("chat_sql")[0]  # not listed for the assistant
    assert "email" in llm.prompts("chat_repair")[0]  # the problem it was told about
    assert message["status"] == "ok"
    assert [c["name"] for c in message["columns"]] == ["id", "name"]  # * stops at the hidden one
    assert all("x.com" not in str(row) for row in message["rows"])
    for sql in (
        "SELECT email FROM customers",
        "SELECT name FROM customers GROUP BY name HAVING max(email) > 'a'",
        "SELECT customers FROM customers",
    ):
        assert boss.post(f"/spaces/{space_id}/query", json={"sql": sql}).status_code == 400, sql


# ── Edit and run, previews, limits, timeouts ─────────────────────────────────


def test_a_person_can_edit_and_run_sql_and_preview_a_table(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    tables = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/tables").json()}

    ran = boss.post(f"/spaces/{space_id}/query", json={"sql": "SELECT count(*) AS n FROM orders"})
    preview = boss.get(f"/spaces/{space_id}/tables/{tables['customers']['id']}/preview")

    assert ran.status_code == 200, ran.text
    assert (ran.json()["rows"], ran.json()["columns"][0]["name"]) == ([[5]], "n")
    assert ran.json()["elapsed_ms"] >= 0 and ran.json()["truncated"] is False
    assert preview.status_code == 200
    assert [r[1] for r in preview.json()["rows"]] == ["Asha", "Ravi", "Mina"]


def test_the_row_limit_is_enforced_and_reported(
    settings: Settings, clean_db: None, data_dir: Path, server: ExternalServer
) -> None:
    gen = build_client(settings, data_dir, query_max_rows=2)
    boss = admin(next(gen))
    space_id, _ = warehouse(boss, server)

    result = boss.post(
        f"/spaces/{space_id}/query", json={"sql": "SELECT id FROM orders ORDER BY id"}
    )

    assert result.status_code == 200
    assert result.json()["rows"] == [[1], [2]] and result.json()["truncated"] is True
    gen.close()


def test_a_query_that_runs_too_long_is_stopped_with_a_clear_message(
    settings: Settings, clean_db: None, data_dir: Path, server: ExternalServer
) -> None:
    gen = build_client(settings, data_dir, query_timeout_seconds=1)
    boss = admin(next(gen))
    space_id, _ = warehouse(boss, server)

    slow = boss.post(
        f"/spaces/{space_id}/query",
        json={"sql": "SELECT count(*) FROM generate_series(1, 5000000000) AS g(n)"},
    )

    assert (slow.status_code, code(slow)) == (400, "query_timeout")
    assert "1 seconds" in slow.json()["error"]["message"]
    quick = boss.post(f"/spaces/{space_id}/query", json={"sql": "SELECT 1 AS one"})
    assert quick.status_code == 200  # nothing was left behind by the stopped query
    gen.close()


# ── The login is checked on every use ────────────────────────────────────────


def test_a_login_that_gains_write_rights_is_blocked_at_the_next_question(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    space_id, cid = warehouse(boss, server)
    admin_sql(settings, "GRANT INSERT ON public.customers TO eoe_reader_t")
    try:
        llm = FakeLLM(chat_sql=[sql_plan(REVENUE)])
        message = ask_sql(boss, space_id, llm, conn_api)
    finally:
        admin_sql(settings, "REVOKE INSERT ON public.customers FROM eoe_reader_t")

    assert message["status"] == "failed" and message["rows"] is None
    assert "no longer read-only" in message["error"]
    assert boss.get(f"/connections/{cid}").json()["status"] == "unsafe"


def test_a_database_that_cannot_be_reached_gives_a_safe_message(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    admin_sql(settings, "ALTER ROLE eoe_reader_t NOLOGIN")
    try:
        message = ask_sql(boss, space_id, FakeLLM(chat_sql=[sql_plan(REVENUE)]), conn_api)
    finally:
        admin_sql(settings, "ALTER ROLE eoe_reader_t LOGIN")

    assert message["status"] == "failed"
    assert "user name or password" in message["error"]
    for leaked in (server.passwords["eoe_reader_t"], "eoe_reader_t", server.host, "NOLOGIN"):
        assert leaked not in str(message)


def test_what_the_person_sees_never_includes_the_real_schema_or_a_password(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    llm = FakeLLM(chat_sql=[sql_plan(REVENUE)])

    message = ask_sql(boss, space_id, llm, conn_api)

    text = str(message)
    assert server.passwords["eoe_reader_t"] not in text
    assert '"public"."orders"' not in text  # the rewritten, internal form
    assert "password" not in text.lower()
    assert all("eoe_reader_t" not in prompt for p in ("chat_sql",) for prompt in llm.prompts(p))


def test_a_viewer_can_ask_but_cannot_edit_the_sql(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    viewer = person(conn_api, boss, "vi@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    use(conn_api, FakeLLM(chat_sql=[sql_plan(REVENUE)]))

    answered = final(events(ask(viewer, space_id, conversation(viewer, space_id), "revenue?")))
    edited = viewer.post(f"/spaces/{space_id}/query", json={"sql": "SELECT 1"})

    assert answered["status"] == "ok" and answered["rows"] == EXPECTED
    assert edited.status_code == 403


def test_pressing_stop_cancels_a_running_query_on_the_database(
    conn_api: TestClient, server: ExternalServer
) -> None:
    import asyncio
    import threading
    import time

    from app.engine import postgres_connect, postgres_engine
    from app.engine.duckdb_engine import CancelToken, QueryCancelledError

    async def attempt() -> float:
        conn = await postgres_connect.open_connection(
            postgres_connect.Credentials(
                server.host,
                server.port,
                server.database,
                "eoe_reader_t",
                server.passwords["eoe_reader_t"],
                "disable",
            ),
            connect_timeout=5,
            statement_timeout_seconds=60,
        )
        token = CancelToken()
        threading.Timer(0.5, token.cancel).start()  # the Stop button, from another thread
        started = time.perf_counter()
        transaction = conn.transaction(readonly=True)
        await transaction.start()
        try:
            with pytest.raises(QueryCancelledError):
                await postgres_engine.run_query(
                    conn,
                    "SELECT count(*) FROM generate_series(1, 5000000000) AS g(n)",
                    max_rows=10,
                    timeout_seconds=60,
                    cancel=token,
                )
        finally:
            await conn.close()
        return time.perf_counter() - started

    assert asyncio.run(attempt()) < 10  # stopped within moments, not after the 60 s timeout


# ── Result rows stay away from the AI service unless the connection allows it ──────────────


def test_by_default_result_rows_are_not_sent_to_the_ai_and_the_summary_is_written_locally(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, cid = warehouse(boss, server)
    assert boss.get(f"/connections/{cid}").json()["share_results_with_ai"] is False
    llm = FakeLLM(chat_sql=[sql_plan(REVENUE)], chat_rewrite=[rewrite("revenue by customer")])
    use(conn_api, llm)
    conv = conversation(boss, space_id)

    first = final(events(ask(boss, space_id, conv, "Revenue by customer?")))

    assert first["status"] == "ok" and first["rows"] == EXPECTED
    assert "chat_explain" not in llm.purposes()  # the explanation call is never made
    assert "Mina" in first["answer"] and "90" in first["answer"]  # written here, from the rows
    assert first["suggestions"] == []
    thoughts = [th["text"] for th in first["thoughts"]]
    assert any("does not share results" in text for text in thoughts)
    assert first["chart"]["type"] == "bar"  # the chart is drawn locally too

    final(events(ask(boss, space_id, conv, "And only the top one?")))

    for prompt in llm.prompts("chat_rewrite") + llm.prompts("chat_sql"):
        assert "Mina" not in prompt and "Highest" not in prompt  # not even through the history


def test_when_an_admin_allows_it_the_ai_writes_the_explanation_from_the_rows(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, cid = warehouse(boss, server)
    allowed = boss.patch(f"/connections/{cid}", json={"share_results_with_ai": True})
    assert allowed.status_code == 200 and allowed.json()["status"] == "ok"  # still tested
    llm = FakeLLM(chat_sql=[sql_plan(REVENUE)])

    message = ask_sql(boss, space_id, llm, conn_api, "Revenue by customer?")

    assert message["answer"] == "Here are the results."  # the (scripted) AI's explanation
    assert "Mina" in llm.prompts("chat_explain")[0]  # it was given the rows
    changes = [
        e for e in boss.get("/connections/audit").json() if e["action"] == "connection.updated"
    ]
    assert changes[0]["detail"] == {"changed": ["share_results_with_ai"]}


# ── Benchmarks on the external database ──────────────────────────────────────


def test_benchmarks_compare_the_real_results_of_the_database(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, _ = warehouse(boss, server)
    by_customer = (
        "SELECT c.name, sum(o.amount) FROM orders o "
        "JOIN customers c ON c.id = o.customer_id GROUP BY c.name"
    )
    assert add_item(boss, space_id, "Revenue per customer?", REVENUE).status_code == 201
    assert add_item(boss, space_id, "Revenue per customer, second try?", REVENUE).status_code == 201
    broken = add_item(boss, space_id, "Nonsense?", "SELECT pg_sleep(5)")
    assert broken.status_code == 400  # the reference goes through the same guard
    use(
        conn_api,
        FakeLLM(
            benchmark_sql=[
                sql_plan(by_customer),  # same numbers as the reference, other names: correct
                sql_plan("SELECT 'all' AS customer, sum(amount) AS revenue FROM orders"),
            ]
        ),
    )

    run = run_all(boss, space_id)

    assert (run["correct"], run["incorrect"], run["accuracy"]) == (1, 1, 0.5)
    first, second = run["results"]
    assert (first["expected_rows"], first["actual_rows"]) == (3, 3)
    assert second["outcome"] == "incorrect" and (
        second["expected_rows"],
        second["actual_rows"],
    ) == (3, 1)
    assert "Mina" not in str(run)  # no value of the database is copied into the results


# ── Permissions: who may reach what ──────────────────────────────────────────


def test_a_space_can_use_only_the_tables_attached_to_it_even_when_the_login_can_read_more(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    space_id, cid = warehouse(boss, server, "public.orders")  # customers is readable, not attached

    for sql in ("SELECT * FROM customers", "SELECT * FROM public.customers"):
        refused = boss.post(f"/spaces/{space_id}/query", json={"sql": sql})
        assert refused.status_code == 400, sql
    assert (
        "no table called 'customers'" in refused.text or "table names on their own" in refused.text
    )
    llm = FakeLLM(
        chat_sql=[sql_plan("SELECT * FROM customers")],
        chat_repair=[sql_plan("SELECT * FROM customers")],
    )
    message = ask_sql(boss, space_id, llm, conn_api)
    assert message["status"] == "failed" and message["rows"] is None

    # A table created later is not available either, until an admin attaches it.
    admin_sql(
        settings,
        "CREATE TABLE public.later_table (id int)",
        "INSERT INTO public.later_table VALUES (1)",
        "GRANT SELECT ON public.later_table TO eoe_reader_t",
    )
    try:
        before = boss.post(f"/spaces/{space_id}/query", json={"sql": "SELECT * FROM later_table"})
        assert before.status_code == 400
        assert attach(boss, space_id, cid, "public.later_table").status_code == 201
        after = boss.post(f"/spaces/{space_id}/query", json={"sql": "SELECT * FROM later_table"})
        assert after.status_code == 200 and after.json()["rows"] == [[1]]
    finally:
        admin_sql(settings, "DROP TABLE IF EXISTS public.later_table")


def test_people_outside_a_space_cannot_reach_its_database_data_or_connection(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id, cid = warehouse(boss, server)
    stranger = person(conn_api, boss, "st@example.com", "editor")  # a global editor, not a member
    other_space = new_space(stranger, "Elsewhere")  # a member of a different space only
    (table,) = [t for t in boss.get(f"/spaces/{space_id}/tables").json() if t["name"] == "orders"]

    attempts = {
        "tables": stranger.get(f"/spaces/{space_id}/tables"),
        "preview": stranger.get(f"/spaces/{space_id}/tables/{table['id']}/preview"),
        "query": stranger.post(f"/spaces/{space_id}/query", json={"sql": "SELECT 1"}),
        "new chat": stranger.post(f"/spaces/{space_id}/conversations", json={"title": None}),
        "benchmarks": stranger.get(f"/spaces/{space_id}/benchmarks"),
    }
    for name, response in attempts.items():
        assert response.status_code == 404, name  # the space is not even visible to them
    for name, response in {
        "connections": stranger.get("/connections"),
        "schema": stranger.get(f"/connections/{cid}/schema"),
        "attach": attach(stranger, other_space, cid, "public.orders"),
        "refresh": stranger.post(f"/spaces/{other_space}/tables/external/refresh"),
    }.items():
        assert response.status_code == 403, name  # connections are for admins only


# ── A size the database has not told us is not "empty" ───────────────────────


def test_a_table_the_database_has_never_analysed_is_queried_not_assumed_empty(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    """PostgreSQL knows a table's size only after it was analysed. That used to be saved as
    "0 rows", the assistant was told so, and it decided the table was empty instead of looking."""
    admin_sql(
        settings,
        "CREATE TABLE public.fresh_table (id int, label text)",
        "INSERT INTO public.fresh_table VALUES (1, 'a'), (2, 'b'), (3, 'c')",
        "GRANT SELECT ON public.fresh_table TO eoe_reader_t",
    )
    try:
        boss = admin(conn_api)
        space_id, _ = warehouse(boss, server, "public.fresh_table")
        (table,) = boss.get(f"/spaces/{space_id}/tables").json()
        meta = boss.get(f"/spaces/{space_id}/metadata").json()
        llm = FakeLLM(chat_sql=[sql_plan("SELECT count(*) AS n FROM fresh_table")])

        message = ask_sql(boss, space_id, llm, conn_api, "How many rows does fresh_table have?")
    finally:
        admin_sql(settings, "DROP TABLE IF EXISTS public.fresh_table")

    assert table["row_count"] == -1 and meta[0]["row_count"] == -1  # not known, not 0
    (prompt,) = llm.prompts("chat_sql")
    assert "Table fresh_table" in prompt and "Table fresh_table (" not in prompt
    assert "0 rows" not in prompt
    assert "only an estimate" in prompt  # and it is told never to conclude emptiness from a size
    assert message["status"] == "ok" and message["rows"] == [[3]]
