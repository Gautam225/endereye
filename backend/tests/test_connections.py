"""External database connections, end to end (needs the test database server).

A throwaway database and four logins are created on the test server: one that can only read, and
three that must be refused (can write, is a superuser, can create objects).
"""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import asyncio
import logging
import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_spaces import ADMIN, Person, admin, api, code, data_dir, external, person  # noqa: F401

from app.core.config import Settings
from app.core.vault import generate_key
from app.main import create_app

pytestmark = pytest.mark.db

EXTERNAL_DB = "eoe_external_test"
ROLES = ("eoe_reader_t", "eoe_writer_t", "eoe_super_t", "eoe_creator_t")


@dataclass(frozen=True)
class ExternalServer:
    host: str
    port: int
    database: str
    passwords: dict[str, str]

    def body(self, role: str = "eoe_reader_t", **overrides: Any) -> dict[str, Any]:
        return {
            "name": f"Warehouse {role}",
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": role,
            "password": self.passwords[role],
            "ssl_mode": "disable",  # the test server runs without SSL; it is on this machine
            **overrides,
        }


async def _provision(settings: Settings, passwords: dict[str, str]) -> None:
    url = settings.sqlalchemy_url
    login = {
        "host": url.host,
        "port": url.port,
        "user": url.username,
        "password": url.password,
    }
    admin_conn = await asyncpg.connect(database="postgres", **login)
    try:
        await _drop(admin_conn)
        await admin_conn.execute(f'CREATE DATABASE "{EXTERNAL_DB}"')
        for role, password in passwords.items():
            extra = " SUPERUSER" if role == "eoe_super_t" else ""
            await admin_conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'{extra}")
    finally:
        await admin_conn.close()

    conn = await asyncpg.connect(database=EXTERNAL_DB, **login)
    try:
        await conn.execute(
            "CREATE TABLE public.orders (id int primary key, amount numeric);"
            "INSERT INTO public.orders VALUES (1, 10), (2, 20);"
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC;"
            f'REVOKE ALL ON DATABASE "{EXTERNAL_DB}" FROM PUBLIC;'
        )
        for role in ROLES:
            await conn.execute(f'GRANT CONNECT ON DATABASE "{EXTERNAL_DB}" TO {role}')
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            await conn.execute(f"GRANT SELECT ON public.orders TO {role}")
        await conn.execute("GRANT INSERT ON public.orders TO eoe_writer_t")
        await conn.execute("GRANT CREATE ON SCHEMA public TO eoe_creator_t")
    finally:
        await conn.close()


async def _drop(conn: asyncpg.Connection) -> None:
    await conn.execute(f'DROP DATABASE IF EXISTS "{EXTERNAL_DB}" WITH (FORCE)')
    for role in ROLES:
        await conn.execute(f"DROP ROLE IF EXISTS {role}")


@pytest.fixture(scope="module")
def server(settings: Settings) -> Iterator[ExternalServer]:
    url = settings.sqlalchemy_url
    passwords = {role: secrets.token_urlsafe(18) for role in ROLES}
    try:
        asyncio.run(_provision(settings, passwords))
    except (asyncpg.PostgresError, OSError) as exc:
        pytest.skip(f"The test server cannot create a database and logins: {type(exc).__name__}")
    yield ExternalServer(url.host or "localhost", url.port or 5432, EXTERNAL_DB, passwords)

    async def cleanup() -> None:
        conn = await asyncpg.connect(
            host=url.host, port=url.port, user=url.username, password=url.password,
            database="postgres",
        )  # fmt: skip
        try:
            await _drop(conn)
        finally:
            await conn.close()

    asyncio.run(cleanup())


def build_client(settings: Settings, data_dir: Path, **updates: Any) -> Iterator[TestClient]:
    custom = settings.model_copy(
        update={
            "data_dir": data_dir,
            "connection_encryption_key": SecretStr(generate_key()),
            "external_db_allow_loopback": True,
            **updates,
        }
    )
    with TestClient(create_app(custom)) as client:
        yield client


@pytest.fixture
def conn_api(settings: Settings, clean_db: None, data_dir: Path) -> Iterator[TestClient]:
    yield from build_client(settings, data_dir)


def create(boss: Person, server: ExternalServer, **kwargs: Any) -> dict[str, Any]:
    response = boss.post("/connections", json=server.body(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()


# ── Creating and reading ─────────────────────────────────────────────────────


def test_a_connection_is_saved_encrypted_and_never_returned_with_its_password(
    conn_api: TestClient, server: ExternalServer, sql: Callable[..., list[Any]]
) -> None:
    boss = admin(conn_api)
    secret = server.passwords["eoe_reader_t"]

    made = create(boss, server)
    listed = boss.get("/connections").json()
    one = boss.get(f"/connections/{made['id']}").json()

    for view in (made, one, listed[0]):
        assert view["has_password"] is True
        assert view["status"] == "untested"
        assert secret not in str(view) and "password" not in {
            k for k in view if k != "has_password"
        }
    (stored,) = sql("SELECT password_encrypted FROM db_connections")[0]
    assert stored.startswith("v1.") and secret not in stored


def test_a_name_can_only_be_used_once(conn_api: TestClient, server: ExternalServer) -> None:
    boss = admin(conn_api)
    create(boss, server)

    again = boss.post("/connections", json=server.body())

    assert (again.status_code, code(again)) == (409, "conflict")


def test_without_an_encryption_key_nothing_can_be_saved_and_the_reason_is_clear(
    settings: Settings, clean_db: None, data_dir: Path, server: ExternalServer
) -> None:
    gen = build_client(settings, data_dir, connection_encryption_key=None)
    client = next(gen)
    boss = admin(client)

    response = boss.post("/connections", json=server.body())

    assert (response.status_code, code(response)) == (503, "vault_not_configured")
    assert "CONNECTION_ENCRYPTION_KEY" in response.json()["error"]["message"]
    gen.close()


# ── Testing a connection ─────────────────────────────────────────────────────


def test_a_read_only_login_connects_and_is_marked_ok(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    made = create(boss, server)

    result = boss.post(f"/connections/{made['id']}/test").json()

    assert (result["ok"], result["status"], result["findings"]) == (True, "ok", [])
    assert result["server_version"]
    assert result["connection"]["status"] == "ok" and result["connection"]["tested_at"]
    assert boss.get(f"/connections/{made['id']}").json()["status"] == "ok"


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("eoe_writer_t", 'can change data in "public"."orders"'),
        ("eoe_super_t", "is a superuser"),
        ("eoe_creator_t", 'can create objects in schema "public"'),
    ],
)
def test_a_login_that_can_change_things_is_refused_with_the_reason(
    conn_api: TestClient, server: ExternalServer, role: str, expected: str
) -> None:
    boss = admin(conn_api)
    made = create(boss, server, role=role)

    result = boss.post(f"/connections/{made['id']}/test").json()

    assert (result["ok"], result["status"]) == (False, "unsafe")
    assert any(expected in finding for finding in result["findings"]), result["findings"]
    assert boss.get(f"/connections/{made['id']}").json()["status"] == "unsafe"


def test_failures_say_what_to_fix_without_exposing_details(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    wrong_password = create(boss, server, name="bad pw", password="not-the-password")
    wrong_database = create(boss, server, name="bad db", database="no_such_database")
    closed_port = create(boss, server, name="closed", port=1)

    results = {
        name: boss.post(f"/connections/{c['id']}/test").json()
        for name, c in (("pw", wrong_password), ("db", wrong_database), ("port", closed_port))
    }

    assert all(r["status"] == "failed" and not r["ok"] for r in results.values())
    assert "user name or password" in results["pw"]["message"]
    assert "does not exist" in results["db"]["message"]
    assert "refused" in results["port"]["message"] or "reached" in results["port"]["message"]
    for result in results.values():
        assert "not-the-password" not in str(result) and server.host not in result["message"]


def test_changing_a_connection_resets_its_test_result_and_keeps_the_password_when_left_out(
    conn_api: TestClient, server: ExternalServer, sql: Callable[..., list[Any]]
) -> None:
    boss = admin(conn_api)
    made = create(boss, server)
    boss.post(f"/connections/{made['id']}/test")
    before = sql("SELECT password_encrypted FROM db_connections")[0][0]

    renamed = boss.patch(f"/connections/{made['id']}", json={"name": "Sales warehouse"}).json()
    moved = boss.patch(f"/connections/{made['id']}", json={"ssl_mode": "verify-ca"}).json()

    assert renamed["status"] == "ok"  # a name does not change what was tested
    assert moved["status"] == "untested" and moved["tested_at"] is None
    assert sql("SELECT password_encrypted FROM db_connections")[0][0] == before
    after_new_password = boss.patch(
        f"/connections/{made['id']}", json={"password": "another-password"}
    )
    assert after_new_password.status_code == 200
    assert sql("SELECT password_encrypted FROM db_connections")[0][0] != before


# ── Where a connection may point ─────────────────────────────────────────────


def test_the_apps_own_database_cannot_be_used_as_a_source(
    conn_api: TestClient, settings: Settings, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    own = settings.sqlalchemy_url

    for host in ("localhost", "127.0.0.1"):
        response = boss.post(
            "/connections",
            json=server.body(
                name=f"own {host}", host=host, port=own.port or 5432, database=own.database
            ),
        )
        assert (response.status_code, code(response)) == (400, "target_not_allowed")
        assert "own database" in response.json()["error"]["message"]


def test_loopback_is_refused_unless_development_allows_it(
    settings: Settings, clean_db: None, data_dir: Path, server: ExternalServer
) -> None:
    gen = build_client(settings, data_dir, external_db_allow_loopback=False)
    boss = admin(next(gen))

    response = boss.post("/connections", json=server.body())

    assert (response.status_code, code(response)) == (400, "target_not_allowed")
    gen.close()


@pytest.mark.parametrize(
    "host",
    ["169.254.169.254", "metadata.google.internal", "0.0.0.0"],
)
def test_metadata_and_unspecified_addresses_are_refused(
    conn_api: TestClient, server: ExternalServer, host: str
) -> None:
    boss = admin(conn_api)

    response = boss.post("/connections", json=server.body(host=host))

    assert (response.status_code, code(response)) == (400, "target_not_allowed")


@pytest.mark.parametrize(
    "host", ["http://db.example.com", "user@db.example.com", "db.example.com/x", "a b"]
)
def test_a_host_that_is_not_a_plain_name_is_not_accepted(
    conn_api: TestClient, server: ExternalServer, host: str
) -> None:
    boss = admin(conn_api)

    response = boss.post("/connections", json=server.body(host=host))

    assert response.status_code == 422
    assert server.passwords["eoe_reader_t"] not in response.text  # input is never echoed


def test_a_saved_connection_is_checked_again_every_time_it_is_tested(
    settings: Settings, clean_db: None, data_dir: Path, server: ExternalServer
) -> None:
    key = SecretStr(generate_key())
    first = build_client(settings, data_dir, connection_encryption_key=key)
    boss = admin(next(first))
    made = create(boss, server)
    first.close()

    # The same saved connection, now in an app that no longer allows hosts on this machine
    second = build_client(
        settings,
        data_dir,
        connection_encryption_key=key,
        external_db_allow_loopback=False,
    )
    client = next(second)
    login = client.post(
        "/api/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    ).json()
    boss_again = Person(client, login["access_token"], login["user"]["id"])

    result = boss_again.post(f"/connections/{made['id']}/test").json()

    assert (result["ok"], result["status"]) == (False, "failed")
    assert "not allowed" in result["message"]
    second.close()


# ── Who may do this ──────────────────────────────────────────────────────────


def test_only_administrators_can_use_connections(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    made = create(boss, server)
    editor = person(conn_api, boss, "ed@example.com", "editor")
    viewer = person(conn_api, boss, "vi@example.com", "viewer")
    cid = made["id"]

    for who in (editor, viewer):
        assert who.get("/connections").status_code == 403
        assert who.get(f"/connections/{cid}").status_code == 403
        assert who.post("/connections", json=server.body(name="x")).status_code == 403
        assert who.patch(f"/connections/{cid}", json={"name": "y"}).status_code == 403
        assert who.post(f"/connections/{cid}/test").status_code == 403
        assert who.delete(f"/connections/{cid}").status_code == 403
        assert who.get("/connections/audit").status_code == 403
    assert conn_api.get("/api/v1/connections").status_code == 401
    assert boss.get(f"/connections/{cid}").json()["name"] == made["name"]


# ── Audit trail and logs ─────────────────────────────────────────────────────


def test_every_change_is_recorded_without_any_secret(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    made = create(boss, server)
    boss.post(f"/connections/{made['id']}/test")
    boss.patch(f"/connections/{made['id']}", json={"password": "brand-new-secret-value"})
    boss.delete(f"/connections/{made['id']}")

    events = boss.get("/connections/audit").json()

    assert [e["action"] for e in reversed(events)] == [
        "connection.created",
        "connection.tested",
        "connection.updated",
        "connection.deleted",
    ]
    updated = next(e for e in events if e["action"] == "connection.updated")
    assert updated["detail"] == {"changed": ["password"]}
    assert all(e["actor_name"] for e in events)
    text = str(events)
    assert "brand-new-secret-value" not in text and server.passwords["eoe_reader_t"] not in text


def test_passwords_never_reach_the_logs(
    conn_api: TestClient, server: ExternalServer, caplog: pytest.LogCaptureFixture
) -> None:
    boss = admin(conn_api)
    secret = server.passwords["eoe_reader_t"]

    with caplog.at_level(logging.DEBUG):
        made = create(boss, server)
        boss.post(f"/connections/{made['id']}/test")
        boss.patch(f"/connections/{made['id']}", json={"password": "another-secret-value"})
        bad = create(boss, server, name="wrong", password="wrong-secret-value")
        boss.post(f"/connections/{bad['id']}/test")

    logged = caplog.text
    for value in (secret, "another-secret-value", "wrong-secret-value"):
        assert value not in logged


def test_an_encrypted_password_moved_to_another_connection_is_not_usable(
    conn_api: TestClient, server: ExternalServer, sql: Callable[..., list[Any]]
) -> None:
    boss = admin(conn_api)
    one = create(boss, server, name="one")
    two = create(boss, server, name="two")
    sql(
        "UPDATE db_connections SET password_encrypted = "
        "(SELECT password_encrypted FROM db_connections WHERE name = 'one') WHERE name = 'two'"
    )

    response = boss.post(f"/connections/{two['id']}/test")

    assert (response.status_code, code(response)) == (500, "vault_error")
    assert server.passwords["eoe_reader_t"] not in response.text
    assert boss.post(f"/connections/{one['id']}/test").json()["status"] == "ok"


def test_deleting_removes_the_connection(conn_api: TestClient, server: ExternalServer) -> None:
    boss = admin(conn_api)
    made = create(boss, server)

    assert boss.delete(f"/connections/{made['id']}").status_code == 204
    assert boss.get(f"/connections/{made['id']}").status_code == 404
    assert boss.get("/connections").json() == []


def test_a_server_without_ssl_is_reported_as_such_when_ssl_is_required(
    conn_api: TestClient, server: ExternalServer
) -> None:
    boss = admin(conn_api)
    made = create(boss, server, ssl_mode="require")

    result = boss.post(f"/connections/{made['id']}/test").json()

    assert (result["ok"], result["status"]) == (False, "failed")
    assert "SSL" in result["message"]
