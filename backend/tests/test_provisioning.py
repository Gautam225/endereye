"""Using a powerful login (like postgres) ONCE to have a read-only login made, so the powerful
password is never saved and never used to answer questions (needs the test server).

The "powerful login" here is the test server's own login. Every login these tests create is
removed afterwards; only ones made by the tests are touched.
"""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from test_connections import EXTERNAL_DB, ExternalServer, conn_api, server  # noqa: F401
from test_external_queries import database_rows
from test_external_tables import admin_sql, objects  # noqa: F401
from test_spaces import Person, admin, code, data_dir, person  # noqa: F401

from app.core.config import Settings

pytestmark = pytest.mark.db

MADE: list[str] = []  # the logins these tests created, to remove afterwards


@pytest.fixture(scope="module", autouse=True)
def remove_created_logins(settings: Settings, objects: None) -> Iterator[None]:
    yield
    url = settings.sqlalchemy_url
    login = {"host": url.host, "port": url.port, "user": url.username, "password": url.password}

    async def cleanup() -> None:
        inside = await asyncpg.connect(database=EXTERNAL_DB, **login)
        try:
            for name in MADE:
                await inside.execute(f'DROP OWNED BY "{name}"')
        finally:
            await inside.close()
        outside = await asyncpg.connect(database="postgres", **login)
        try:
            for name in MADE:
                await outside.execute(f'DROP ROLE IF EXISTS "{name}"')
        finally:
            await outside.close()

    asyncio.run(cleanup())


def powerful(settings: Settings) -> tuple[str, str]:
    url = settings.sqlalchemy_url
    return url.username or "", url.password or ""


def provision_body(server: ExternalServer, settings: Settings, **overrides: Any) -> dict[str, Any]:
    user, password = powerful(settings)
    return {
        "name": "Provisioned",
        "host": server.host,
        "port": server.port,
        "database": server.database,
        "admin_username": user,
        "admin_password": password,
        "ssl_mode": "disable",
        **overrides,
    }


def made_logins(settings: Settings) -> int:
    return database_rows(
        settings, "SELECT count(*) FROM pg_roles WHERE starts_with(rolname, 'eoe_reader_')"
    )[0][0]


def provision(boss: Person, server: ExternalServer, settings: Settings, **overrides: Any) -> Any:
    response = boss.post(
        "/connections/provision", json=provision_body(server, settings, **overrides)
    )
    if response.status_code == 201:
        MADE.append(response.json()["connection"]["username"])
    return response


# ── Making the login ─────────────────────────────────────────────────────────


def test_a_read_only_login_is_made_and_the_powerful_password_is_not_kept(
    conn_api: TestClient,
    server: ExternalServer,
    settings: Settings,
    sql: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    boss = admin(conn_api)
    _, secret = powerful(settings)

    with caplog.at_level(logging.DEBUG):
        response = provision(boss, server, settings)

    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["ok"], result["status"], result["findings"]) == (True, "ok", [])
    connection = result["connection"]
    login = connection["username"]
    assert login.startswith("eoe_reader_") and login != powerful(settings)[0]
    # The powerful password is nowhere: not in the answer, the saved row, the audit trail or logs.
    assert secret not in response.text and secret not in caplog.text
    (stored,) = sql("SELECT password_encrypted FROM db_connections")[0]
    assert stored.startswith("v1.") and secret not in stored
    events = str(boss.get("/connections/audit").json())
    assert "connection.provisioned" in events and login in events and secret not in events

    role = database_rows(
        settings,
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolcanlogin "
        f"FROM pg_roles WHERE rolname = '{login}'",
    )
    assert role == [[False, False, False, False, False, True]]
    schema = boss.get(f"/connections/{connection['id']}/schema")
    refs = {f"{t['schema']}.{t['name']}" for t in schema.json()}
    assert {"public.orders", "public.customers", "finance.invoices"} <= refs


def test_the_schemas_the_new_login_may_read_can_be_chosen(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)

    response = provision(boss, server, settings, schemas=["finance"])

    assert response.status_code == 201, response.text
    cid = response.json()["connection"]["id"]
    refs = {f"{t['schema']}.{t['name']}" for t in boss.get(f"/connections/{cid}/schema").json()}
    assert refs and all(ref.startswith("finance.") for ref in refs)  # not public.orders


def test_a_schema_that_does_not_exist_or_has_nothing_to_read_leaves_no_login_behind(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    before = made_logins(settings)
    admin_sql(settings, "CREATE SCHEMA emptied")
    try:
        missing = provision(boss, server, settings, schemas=["no_such_schema"])
        nothing = provision(boss, server, settings, schemas=["emptied"])
    finally:
        admin_sql(settings, "DROP SCHEMA IF EXISTS emptied")

    assert (missing.status_code, code(missing)) == (400, "provision_failed")
    assert "do not exist" in missing.json()["error"]["message"]
    assert (nothing.status_code, code(nothing)) == (400, "provision_failed")
    assert "not be able to read any table" in nothing.json()["error"]["message"]
    assert made_logins(settings) == before  # the transaction was rolled back
    assert boss.get("/connections").json() == []


# ── Refusals, with nothing left behind ───────────────────────────────────────


def test_a_wrong_admin_password_is_refused_safely_and_makes_nothing(
    conn_api: TestClient,
    server: ExternalServer,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    boss = admin(conn_api)
    before = made_logins(settings)

    with caplog.at_level(logging.DEBUG):
        response = provision(boss, server, settings, admin_password="not-the-password")

    assert (response.status_code, code(response)) == (400, "provision_failed")
    assert "user name or password" in response.json()["error"]["message"]
    assert "not-the-password" not in response.text and "not-the-password" not in caplog.text
    assert made_logins(settings) == before and boss.get("/connections").json() == []


def test_a_login_that_cannot_create_logins_is_refused_with_advice(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    before = made_logins(settings)

    response = provision(
        boss,
        server,
        settings,
        admin_username="eoe_reader_t",  # a read-only login: it may not create other logins
        admin_password=server.passwords["eoe_reader_t"],
    )

    assert (response.status_code, code(response)) == (400, "provision_failed")
    assert "can't create other logins" in response.json()["error"]["message"]
    assert made_logins(settings) == before


def test_a_name_already_in_use_is_refused_before_any_login_is_made(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    assert provision(boss, server, settings).status_code == 201
    before = made_logins(settings)

    again = provision(boss, server, settings)

    assert (again.status_code, code(again)) == (409, "conflict")
    assert made_logins(settings) == before


def test_only_administrators_can_make_logins(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    editor = person(conn_api, boss, "ed@example.com", "editor")
    before = made_logins(settings)

    refused = editor.post("/connections/provision", json=provision_body(server, settings))
    one_click = editor.post(
        f"/connections/{'0' * 8}-0000-0000-0000-{'0' * 12}/make-read-only", json={}
    )

    assert refused.status_code == 403 and one_click.status_code == 403
    assert made_logins(settings) == before


# ── Fixing a blocked connection ──────────────────────────────────────────────


def test_a_blocked_connection_is_switched_to_a_read_only_login_and_forgets_the_powerful_one(
    conn_api: TestClient,
    server: ExternalServer,
    settings: Settings,
    sql: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    boss = admin(conn_api)
    user, secret = powerful(settings)
    made = boss.post(
        "/connections", json=server.body(name="Powerful", username=user, password=secret)
    ).json()
    blocked = boss.post(f"/connections/{made['id']}/test").json()
    assert blocked["status"] == "unsafe"  # a superuser is refused, as it should be
    (before,) = sql("SELECT password_encrypted FROM db_connections")[0]

    with caplog.at_level(logging.DEBUG):
        fixed = boss.post(f"/connections/{made['id']}/make-read-only", json={})
    assert fixed.status_code == 200, fixed.text
    MADE.append(fixed.json()["connection"]["username"])

    result = fixed.json()
    assert (result["ok"], result["status"]) == (True, "ok")
    assert result["connection"]["username"].startswith("eoe_reader_")
    assert result["connection"]["id"] == made["id"]  # the same connection, a safer login
    (after,) = sql("SELECT password_encrypted FROM db_connections")[0]
    assert after != before  # the powerful password was replaced, not kept
    assert secret not in fixed.text and secret not in caplog.text
    events = [
        e
        for e in boss.get("/connections/audit").json()
        if e["action"] == "connection.made_read_only"
    ]
    assert events[0]["detail"]["previous_login"] == user and secret not in str(events)
    assert boss.get(f"/connections/{made['id']}/schema").status_code == 200  # usable now


def test_a_connection_that_is_not_blocked_is_left_alone(
    conn_api: TestClient, server: ExternalServer, settings: Settings
) -> None:
    boss = admin(conn_api)
    ok = provision(boss, server, settings).json()["connection"]
    before = made_logins(settings)

    again = boss.post(f"/connections/{ok['id']}/make-read-only", json={})

    assert (again.status_code, code(again)) == (409, "not_unsafe")
    assert made_logins(settings) == before  # no needless login was made
