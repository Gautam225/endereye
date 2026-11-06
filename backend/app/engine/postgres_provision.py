"""Making a read-only login for an external PostgreSQL database.

A login that can change data is refused as a connection, however convenient: the database's own
permissions are the real safety wall. This module is the way to keep using a powerful login (like
`postgres`) without ever using it for questions: it is used **once**, here, to create a new login
that can only SELECT, and then it is forgotten. The caller stores only the new login.

What is created:
- A login with a random name (`eoe_reader_1a2b3c4d`) and a random password made here, never typed
  by anyone. It cannot be a superuser, create databases or roles, replicate, or bypass row-level
  security. It can connect to this database and SELECT from the tables of the chosen schemas
  (every non-system schema when none are chosen). It gets no right to create anything.
- Nothing else is changed: no existing login, table or setting is touched, and `PUBLIC`'s
  privileges are left alone.
- Everything happens in one transaction, so a failure leaves no half-made login behind.

New tables created later are not readable by the new login until it is granted them (and an
admin attaches them to a space).
"""

import logging
import secrets
from dataclasses import dataclass, field

import asyncpg

from app.core.errors import AppError
from app.engine import postgres_connect
from app.engine.postgres_connect import Credentials
from app.engine.postgres_discovery import quote_ident

logger = logging.getLogger(__name__)

ROLE_PREFIX = "eoe_reader_"
TIMEOUT_SECONDS = 30


class ProvisionError(AppError):
    """The login could not be made. The message is safe to show."""

    status_code = 400
    code = "provision_failed"


@dataclass(frozen=True, slots=True)
class Provisioned:
    username: str
    password: str = field(repr=False)  # never printed, even by accident
    schemas: tuple[str, ...]
    tables: int


async def create_reader(
    admin: Credentials, *, connect_timeout: float, schemas: list[str] | None = None
) -> Provisioned:
    """Use `admin` once to create a read-only login. Raises ProvisionError with a safe message."""
    try:
        conn = await postgres_connect.open_connection(
            admin,
            connect_timeout=connect_timeout,
            statement_timeout_seconds=TIMEOUT_SECONDS,
            read_only=False,
        )
    except Exception as exc:
        _category, message = postgres_connect.safe_error(exc, connect_timeout)
        raise ProvisionError(message) from None

    try:
        async with conn.transaction():
            return await _create(conn, schemas)
    except ProvisionError:
        raise
    except asyncpg.InsufficientPrivilegeError:
        raise ProvisionError(
            "This login is not allowed to create another login or to grant access to the tables."
        ) from None
    except asyncpg.PostgresError as exc:
        logger.info("Creating a read-only login failed", extra={"sqlstate": exc.sqlstate})
        raise ProvisionError(
            f"The database could not create the login (code {exc.sqlstate or '?'})."
        ) from None
    finally:
        await conn.close(timeout=5)


async def _create(conn: asyncpg.Connection, schemas: list[str] | None) -> Provisioned:
    me = await conn.fetchrow(
        "SELECT rolsuper, rolcreaterole FROM pg_roles WHERE rolname = current_user"
    )
    if me is None or not (me["rolsuper"] or me["rolcreaterole"]):
        raise ProvisionError(
            "This login can't create other logins. Use one that can (like postgres), or make the "
            "read-only login yourself with the script on this page."
        )

    available = [
        row["nspname"]
        for row in await conn.fetch(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' ORDER BY 1"
        )
    ]
    chosen = list(dict.fromkeys(schemas)) if schemas else available
    unknown = [name for name in chosen if name not in available]
    if unknown:
        raise ProvisionError("These schemas do not exist: " + ", ".join(unknown[:5]) + ".")
    if not chosen:
        raise ProvisionError("The database has no schema to read.")

    database = await conn.fetchval("SELECT current_database()")
    name = ROLE_PREFIX + secrets.token_hex(4)
    # Made here from letters, digits, "_" and "-" only, so it is safe inside quotes.
    password = secrets.token_urlsafe(24)
    role = quote_ident(name)

    await conn.execute(
        f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
        f"NOBYPASSRLS NOINHERIT PASSWORD '{password}'"
    )
    await conn.execute(f"GRANT CONNECT ON DATABASE {quote_ident(database)} TO {role}")
    for schema in chosen:
        await conn.execute(f"GRANT USAGE ON SCHEMA {quote_ident(schema)} TO {role}")
        await conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {quote_ident(schema)} TO {role}")

    readable = await conn.fetchval(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY($1::text[]) AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
        "AND has_table_privilege($2::name, c.oid, 'SELECT')",
        chosen,
        name,
    )
    if not readable:
        # Nothing to read (an empty schema, or this login may not grant what it does not own).
        # Raising rolls the whole transaction back: no login is left behind.
        raise ProvisionError(
            "The new login would not be able to read any table. This login may not be allowed "
            "to grant access to tables it does not own, or the chosen schemas have no tables."
        )
    return Provisioned(name, password, tuple(chosen), int(readable))
