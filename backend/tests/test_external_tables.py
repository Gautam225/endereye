"""Reading an external database's structure and giving tables to a space (needs the test server).

The database is the throwaway one from test_connections, plus tables that cover the cases:
descriptions, a foreign key, a view, a second schema, a key over two columns, a table the login
may not read, a column it may not read, and a schema it may not use.
"""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import asyncio
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from test_connections import EXTERNAL_DB, ExternalServer, conn_api, create, server  # noqa: F401
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.core.config import Settings
from app.services import external_tables

pytestmark = pytest.mark.db

OBJECTS = [
    "CREATE TABLE public.customers (id int PRIMARY KEY, name text, email text)",
    "COMMENT ON TABLE public.customers IS 'One row per customer'",
    "COMMENT ON COLUMN public.customers.email IS 'Contact email'",
    "ALTER TABLE public.orders ADD COLUMN customer_id int REFERENCES public.customers(id)",
    "COMMENT ON TABLE public.orders IS 'Customer orders'",
    "CREATE TABLE public.hr_secrets (id int, note text)",  # the login has no grant on this
    "CREATE TABLE public.people (id int PRIMARY KEY, name text, salary numeric)",
    "CREATE VIEW public.order_totals AS "
    "SELECT customer_id, sum(amount) AS total FROM public.orders GROUP BY 1",
    "CREATE SCHEMA finance",
    "CREATE TABLE finance.invoices (id int PRIMARY KEY, order_id int)",
    "CREATE TABLE finance.line_items (order_id int, line int, PRIMARY KEY (order_id, line))",
    "CREATE TABLE finance.line_notes (order_id int, line int, "
    "FOREIGN KEY (order_id, line) REFERENCES finance.line_items (order_id, line))",
    "CREATE SCHEMA hidden",  # the login has no USAGE on this schema
    "CREATE TABLE hidden.stuff (id int)",
    "GRANT SELECT ON public.customers, public.order_totals TO eoe_reader_t",
    "GRANT SELECT (id, name) ON public.people TO eoe_reader_t",
    "GRANT USAGE ON SCHEMA finance TO eoe_reader_t",
    "GRANT SELECT ON finance.invoices, finance.line_items, finance.line_notes TO eoe_reader_t",
    "ANALYZE",
]


def admin_sql(settings: Settings, *statements: str) -> None:
    """Run statements in the external database as its owner (to set up, or to change it)."""
    url = settings.sqlalchemy_url

    async def run() -> None:
        conn = await asyncpg.connect(
            host=url.host, port=url.port, user=url.username, password=url.password,
            database=EXTERNAL_DB,
        )  # fmt: skip
        try:
            for statement in statements:
                await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(run())


@pytest.fixture(scope="module", autouse=True)
def objects(settings: Settings, server: ExternalServer) -> None:
    admin_sql(settings, *OBJECTS)


def ready(boss: Person, server: ExternalServer, **kwargs: Any) -> str:
    """A saved connection that passed its test. Returns its id."""
    made = create(boss, server, **kwargs)
    result = boss.post(f"/connections/{made['id']}/test").json()
    assert result["status"] == "ok", result
    return made["id"]


def refs(*names: str) -> list[dict[str, str]]:
    return [dict(zip(("schema", "name"), n.split("."), strict=True)) for n in names]


def attach(boss: Person, space_id: str, connection_id: str, *names: str, **extra: Any) -> Any:
    return boss.post(
        f"/spaces/{space_id}/tables/external",
        json={"connection_id": connection_id, "tables": refs(*names), **extra},
    )


# ── Reading the structure ────────────────────────────────────────────────────


def test_only_what_the_login_may_read_is_listed_with_its_columns_keys_and_comments(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)

    found = boss.get(f"/connections/{cid}/schema")

    assert found.status_code == 200, found.text
    by = {f"{t['schema']}.{t['name']}": t for t in found.json()}
    assert {"public.orders", "public.customers", "public.people", "public.order_totals"} <= set(by)
    assert "finance.invoices" in by
    assert not any(ref.startswith(("pg_", "information_schema", "hidden.")) for ref in by)
    assert "public.hr_secrets" not in by  # no SELECT on the table

    customers = by["public.customers"]
    assert (customers["kind"], customers["comment"]) == ("table", "One row per customer")
    assert [(c["name"], c["primary_key"]) for c in customers["columns"]] == [
        ("id", True),
        ("name", False),
        ("email", False),
    ]
    assert customers["columns"][2]["comment"] == "Contact email"
    assert by["public.order_totals"]["kind"] == "view"
    assert [c["name"] for c in by["public.people"]["columns"]] == ["id", "name"]  # not salary

    (fk,) = by["public.orders"]["foreign_keys"]
    assert (fk["columns"], fk["ref_table"], fk["ref_columns"], fk["supported"]) == (
        ["customer_id"],
        "customers",
        ["id"],
        True,
    )
    (composite,) = by["finance.line_notes"]["foreign_keys"]
    assert composite["supported"] is False  # a join is one column to one column


def test_the_structure_can_only_be_read_through_a_tested_connection_by_an_admin(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    untested = create(boss, server)["id"]
    editor = person(conn_api, boss, "ed@example.com", "editor")
    cid = ready(boss, server, name="second")

    not_tested = boss.get(f"/connections/{untested}/schema")

    assert (not_tested.status_code, code(not_tested)) == (409, "connection_not_tested")
    assert editor.get(f"/connections/{cid}/schema").status_code == 403


def test_a_login_that_gains_write_rights_after_its_test_is_blocked_on_the_next_use(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    admin_sql(settings, "GRANT INSERT ON public.customers TO eoe_reader_t")
    try:
        blocked = boss.get(f"/connections/{cid}/schema")
    finally:
        admin_sql(settings, "REVOKE INSERT ON public.customers FROM eoe_reader_t")

    assert (blocked.status_code, code(blocked)) == (409, "connection_unsafe")
    assert boss.get(f"/connections/{cid}").json()["status"] == "unsafe"
    assert boss.get(f"/connections/{cid}/schema").status_code == 409  # stays blocked until retested


# ── Giving tables to a space ─────────────────────────────────────────────────


def test_attached_tables_keep_the_databases_descriptions_and_foreign_keys_become_confirmed_joins(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)

    response = attach(boss, space_id, cid, "public.orders", "public.customers")

    assert response.status_code == 201, response.text
    body = response.json()
    tables = {t["name"]: t for t in body["tables"]}
    assert set(tables) == {"orders", "customers"}
    assert (tables["orders"]["source_type"], tables["orders"]["source_ref"]) == (
        "external",
        "public.orders",
    )
    assert tables["orders"]["connection_id"] == cid
    assert tables["orders"]["description"] == "Customer orders"
    assert tables["orders"]["profiled_at"] is not None
    assert body["joins_created"] == 1 and body["skipped_foreign_keys"] == []

    (join,) = boss.get(f"/spaces/{space_id}/joins").json()
    assert (join["left_table"], join["left_column"]) == ("orders", "customer_id")
    assert (join["right_table"], join["right_column"]) == ("customers", "id")
    assert (join["source"], join["confirmed"], join["relationship"]) == (
        "foreign_key",
        True,
        "many_to_one",
    )

    meta = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/metadata").json()}
    email = next(c for c in meta["customers"]["columns"] if c["name"] == "email")
    assert email["description"] == "Contact email"
    # Customer data is not shared with the AI unless an admin switches it on for the column
    assert all(
        not c["share_values"] and not c["entity_matching"]
        for t in meta.values()
        for c in t["columns"]
    )
    assert all(c["stats"] is None for t in meta.values() for c in t["columns"])  # nothing profiled


def test_names_for_other_schemas_a_composite_key_and_nothing_copied(
    conn_api: TestClient, server: ExternalServer, sql: Any
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)

    response = attach(
        boss, space_id, cid, "finance.line_items", "finance.line_notes", "finance.invoices"
    )

    body = response.json()
    assert sorted(t["name"] for t in body["tables"]) == [
        "finance_invoices",
        "finance_line_items",
        "finance_line_notes",
    ]
    assert body["joins_created"] == 0
    assert body["skipped_foreign_keys"] == ["finance.line_notes: line_notes_order_id_line_fkey"]
    # Only descriptions are stored: no file, no copy of any row
    assert sql("SELECT DISTINCT storage_path FROM space_tables") == [("",)]


def test_a_table_the_login_cannot_read_or_that_does_not_exist_cannot_be_attached(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)

    for name in ("public.hr_secrets", "hidden.stuff", "public.nope"):
        response = attach(boss, space_id, cid, name)
        assert (response.status_code, code(response)) == (404, "not_found"), name
    assert boss.get(f"/spaces/{space_id}/tables").json() == []


def test_a_space_uses_files_or_one_database_and_stays_within_its_limits(
    conn_api: TestClient, server: ExternalServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    other = ready(boss, server, name="Other warehouse")
    with_files = new_space(boss, "Files")
    assert boss.upload(with_files, "sales.csv", b"a,b\n1,2\n").status_code == 201
    space_id = new_space(boss, "Warehouse")

    mixed = attach(boss, with_files, cid, "public.orders")
    assert (mixed.status_code, code(mixed)) == (409, "space_has_files")
    assert attach(boss, space_id, cid, "public.orders").status_code == 201
    twice = attach(boss, space_id, cid, "public.orders")
    assert (twice.status_code, code(twice)) == (409, "attached")
    elsewhere = attach(boss, space_id, other, "public.customers")
    assert (elsewhere.status_code, code(elsewhere)) == (409, "space_other_connection")

    monkeypatch.setattr(external_tables, "MAX_EXTERNAL_TABLES", 2)
    too_many = attach(boss, space_id, cid, "public.customers", "public.people")
    assert (too_many.status_code, code(too_many)) == (400, "too_many_tables")
    duplicate = boss.post(
        f"/spaces/{space_id}/tables/external",
        json={"connection_id": cid, "tables": refs("public.people", "public.people")},
    )
    assert (duplicate.status_code, code(duplicate)) == (400, "duplicate_table")


def test_only_administrators_can_attach_or_refresh(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)
    editor = person(conn_api, boss, "ed@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{editor.id}", json={"role": "editor"})

    assert attach(editor, space_id, cid, "public.orders").status_code == 403
    assert editor.post(f"/spaces/{space_id}/tables/external/refresh").status_code == 403


def test_a_table_can_be_taken_out_of_a_space_without_touching_the_database(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)
    (table,) = attach(boss, space_id, cid, "public.customers").json()["tables"]

    assert boss.delete(f"/spaces/{space_id}/tables/{table['id']}").status_code == 204

    assert boss.get(f"/spaces/{space_id}/tables").json() == []
    still = boss.get(f"/connections/{cid}/schema").json()
    assert any(t["name"] == "customers" for t in still)


# ── File-only features refuse external tables instead of running on the wrong engine ───────


def test_file_only_features_refuse_external_tables(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)
    (table,) = attach(boss, space_id, cid, "public.customers").json()["tables"]

    attempts = {
        "profile": boss.post(f"/spaces/{space_id}/tables/{table['id']}/profile"),
        "joins": boss.post(f"/spaces/{space_id}/joins/detect"),
    }

    for name, response in attempts.items():
        assert (response.status_code, code(response)) == (409, "external_table"), name


def test_a_connection_in_use_cannot_be_deleted_or_pointed_elsewhere(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)
    (table,) = attach(boss, space_id, cid, "public.customers").json()["tables"]

    delete = boss.delete(f"/connections/{cid}")
    moved = boss.patch(f"/connections/{cid}", json={"database": "another_db"})
    renamed = boss.patch(f"/connections/{cid}", json={"name": "Warehouse (main)"})

    assert (delete.status_code, code(delete)) == (409, "connection_in_use")
    assert (moved.status_code, code(moved)) == (409, "connection_in_use")
    assert renamed.status_code == 200
    boss.delete(f"/spaces/{space_id}/tables/{table['id']}")
    assert boss.delete(f"/connections/{cid}").status_code == 204


def test_the_database_refuses_an_external_table_without_a_connection(
    conn_api: TestClient, sql: Any
) -> None:
    boss = admin(conn_api)
    space_id = new_space(boss)

    with pytest.raises(Exception, match="ck_space_tables_connection"):
        sql(
            "INSERT INTO space_tables (id, space_id, name, source_type, source_ref, storage_path,"
            " columns, row_count) VALUES (gen_random_uuid(), :space, 'x', 'external', 'a.b', '',"
            " '[]', 0)",
            {"space": space_id},
        )


# ── Keeping up with changes in the database ──────────────────────────────────


def test_a_refresh_shows_changes_first_then_applies_them_and_keeps_edits_and_manual_joins(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)
    admin_sql(
        settings,
        "CREATE TABLE public.scratch (id int PRIMARY KEY, tmp text, "
        "ref_id int CONSTRAINT scratch_ref_fk REFERENCES public.customers(id))",
        "GRANT SELECT ON public.scratch TO eoe_reader_t",
    )
    try:
        made = attach(boss, space_id, cid, "public.customers", "public.orders", "public.scratch")
        assert made.status_code == 201, made.text
        ids = {t["name"]: t["id"] for t in made.json()["tables"]}
        meta = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/metadata").json()}
        id_column = next(c for c in meta["customers"]["columns"] if c["name"] == "id")
        boss.patch(
            f"/spaces/{space_id}/tables/{ids['customers']}/columns/{id_column['id']}",
            json={"description": "Customer number, set by an editor"},
        )
        manual = boss.post(
            f"/spaces/{space_id}/joins",
            json={
                "left_table_id": ids["scratch"],
                "left_column": "id",
                "right_table_id": ids["orders"],
                "right_column": "id",
                "relationship": "one_to_one",
            },
        )
        assert manual.status_code == 201, manual.text
        assert len(boss.get(f"/spaces/{space_id}/joins").json()) == 3

        admin_sql(
            settings,
            "ALTER TABLE public.customers ADD COLUMN phone text",
            "ALTER TABLE public.customers ALTER COLUMN name TYPE varchar(50)",
            "ALTER TABLE public.scratch DROP COLUMN tmp",
            "ALTER TABLE public.scratch DROP CONSTRAINT scratch_ref_fk",
        )

        preview = boss.post(f"/spaces/{space_id}/tables/external/refresh").json()

        assert preview["applied"] is False and preview["joins_removed"] == 1
        changed = {t["name"]: t for t in preview["tables"]}
        assert changed["customers"]["status"] == "changed"
        assert changed["customers"]["added_columns"] == ["phone"]
        assert changed["customers"]["type_changes"] == [
            {"column": "name", "from_type": "text", "to_type": "character varying(50)"}
        ]
        assert changed["scratch"]["removed_columns"] == ["tmp"]
        assert changed["orders"]["status"] == "unchanged"
        names = [
            c["name"] for t in boss.get(f"/spaces/{space_id}/metadata").json() for c in t["columns"]
        ]
        assert "phone" not in names and "tmp" in names  # a preview changes nothing
        assert len(boss.get(f"/spaces/{space_id}/joins").json()) == 3

        applied = boss.post(f"/spaces/{space_id}/tables/external/refresh?apply=true").json()

        assert applied["applied"] is True and applied["joins_removed"] == 1
        meta = {t["name"]: t for t in boss.get(f"/spaces/{space_id}/metadata").json()}
        columns = {c["name"]: c for c in meta["customers"]["columns"]}
        assert "phone" in columns and columns["name"]["type"] == "character varying(50)"
        assert columns["id"]["description"] == "Customer number, set by an editor"
        assert "phone" in columns and not columns["phone"]["share_values"]
        assert [c["name"] for c in meta["scratch"]["columns"]] == ["id", "ref_id"]
        joins = boss.get(f"/spaces/{space_id}/joins").json()
        assert sorted(j["source"] for j in joins) == ["foreign_key", "manual"]

        admin_sql(settings, "DROP TABLE public.scratch")
        gone = boss.post(f"/spaces/{space_id}/tables/external/refresh?apply=true").json()

        assert {t["name"]: t["status"] for t in gone["tables"]}["scratch"] == "missing"
        still_there = {t["name"] for t in boss.get(f"/spaces/{space_id}/tables").json()}
        assert "scratch" in still_there  # a refresh never deletes a table
    finally:
        admin_sql(
            settings,
            "DROP TABLE IF EXISTS public.scratch",
            "ALTER TABLE public.customers DROP COLUMN IF EXISTS phone",
            "ALTER TABLE public.customers ALTER COLUMN name TYPE text",
        )


def test_attaching_and_refreshing_are_recorded_without_secrets(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    cid = ready(boss, server)
    space_id = new_space(boss)
    attach(boss, space_id, cid, "public.customers")
    boss.post(f"/spaces/{space_id}/tables/external/refresh?apply=true")

    events_ = boss.get("/connections/audit").json()

    actions = [e["action"] for e in reversed(events_)]
    assert "space.tables_attached" in actions and "space.tables_refreshed" in actions
    attached = next(e for e in events_ if e["action"] == "space.tables_attached")
    assert attached["detail"]["tables"] == ["public.customers"]
    assert server.passwords["eoe_reader_t"] not in str(events_)


def test_a_refresh_needs_tables_from_a_database(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    space_id = new_space(boss)

    response = boss.post(f"/spaces/{space_id}/tables/external/refresh")

    assert (response.status_code, code(response)) == (400, "no_external")


def test_a_table_name_with_a_dot_is_refused_because_it_cannot_be_stored_safely(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    admin_sql(
        settings,
        'CREATE TABLE public."odd.name" (id int)',
        'GRANT SELECT ON public."odd.name" TO eoe_reader_t',
    )
    try:
        cid = ready(boss, server)
        space_id = new_space(boss)
        response = boss.post(
            f"/spaces/{space_id}/tables/external",
            json={"connection_id": cid, "tables": [{"schema": "public", "name": "odd.name"}]},
        )
    finally:
        admin_sql(settings, 'DROP TABLE IF EXISTS public."odd.name"')

    assert (response.status_code, code(response)) == (400, "unsupported_name")
