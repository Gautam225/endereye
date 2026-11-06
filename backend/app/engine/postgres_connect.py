"""Opening and testing a connection to an external PostgreSQL server.

Rules this module keeps, because the server is not ours:
- A new connection for each job, closed when the job ends. Nothing is pooled or kept open.
- Everything runs in a READ ONLY transaction, with short statement, lock and idle timeouts.
- The password is used only to open the connection. Errors are turned into a few fixed, safe
  messages: the driver's own text can contain host names, user names and queries, so it is
  never passed on.
- A login that could change data (or is a superuser, or can read server files) is reported as
  unsafe. SQL checking is only the first wall; a database login that can only read is the real
  one, so a connection whose login is too powerful is not used.
"""

import asyncio
import logging
import socket
import ssl
from dataclasses import dataclass, field

import asyncpg

logger = logging.getLogger(__name__)

APPLICATION_NAME = "eye-of-ender"
POWERFUL_ROLES = (
    "pg_read_server_files",
    "pg_write_server_files",
    "pg_execute_server_program",
    "pg_write_all_data",
    "pg_signal_backend",
)
MAX_FINDINGS = 12


@dataclass(frozen=True, slots=True)
class Credentials:
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)  # never printed, even by accident
    ssl_mode: str = "verify-full"


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    ok: bool
    status: str  # "ok", "failed" or "unsafe"
    message: str  # safe to show to an admin
    server_version: str | None = None
    findings: tuple[str, ...] = ()


def ssl_context(mode: str) -> ssl.SSLContext | bool:
    """verify-full: certificate and host name are checked. verify-ca: the certificate only.
    require: encrypted, but the server is not verified. disable: no encryption."""
    if mode == "disable":
        return False
    context = ssl.create_default_context()
    if mode == "verify-full":
        return context
    context.check_hostname = False
    if mode == "require":
        context.verify_mode = ssl.CERT_NONE
    return context


def safe_error(exc: BaseException, timeout: float) -> tuple[str, str]:
    """(category, message) for a failed connection. The message never contains driver text."""
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return "timeout", f"The database did not answer within {timeout:g} seconds."
    if isinstance(exc, ssl.SSLError | ssl.CertificateError):
        return "tls", (
            "A secure connection could not be made. Check the SSL mode and that the server's "
            "certificate is valid for this host name."
        )
    if (
        isinstance(exc, ConnectionError)
        and not isinstance(exc, ConnectionRefusedError)
        and "ssl" in str(exc).lower()
    ):
        return "tls", (
            "The server does not accept secure (SSL) connections. Turn SSL on in the database, "
            "or (only on a trusted private network) set the SSL mode to disable."
        )
    if isinstance(exc, socket.gaierror):
        return "dns", "The host name could not be found."
    if isinstance(exc, ConnectionRefusedError):
        return "refused", "The database refused the connection. Check the host and port."
    if isinstance(
        exc, asyncpg.InvalidPasswordError | asyncpg.InvalidAuthorizationSpecificationError
    ):
        return "auth", "The user name or password was not accepted."
    if isinstance(exc, asyncpg.InvalidCatalogNameError):
        return "database", "That database does not exist on the server."
    if isinstance(exc, asyncpg.PostgresError):
        return "database_error", f"The database reported an error (code {exc.sqlstate})."
    if isinstance(exc, OSError):
        return "network", "The database could not be reached."
    return "unknown", "The connection failed for an unknown reason."


async def open_connection(
    credentials: Credentials,
    *,
    connect_timeout: float,
    statement_timeout_seconds: float,
    read_only: bool = True,
) -> asyncpg.Connection:
    """A read-only session (unless `read_only` is False, which only the one-time creation of a
    read-only login uses). The caller must close it."""
    milliseconds = str(int(statement_timeout_seconds * 1000))
    return await asyncpg.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        database=credentials.database,
        ssl=ssl_context(credentials.ssl_mode),
        timeout=connect_timeout,
        command_timeout=statement_timeout_seconds + 5,
        statement_cache_size=0,
        server_settings={
            "application_name": APPLICATION_NAME,
            **({"default_transaction_read_only": "on"} if read_only else {}),
            "statement_timeout": milliseconds,
            "lock_timeout": "5000",
            "idle_in_transaction_session_timeout": "30000",
        },
    )


async def role_findings(conn: asyncpg.Connection) -> list[str]:
    """Why the login is too powerful, in plain words. Empty means read-only as far as the
    server's own privilege tables say."""
    findings: list[str] = []
    role = await conn.fetchrow(
        "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    )
    if role is not None:
        for column, text in (
            ("rolsuper", "is a superuser"),
            ("rolcreaterole", "can create roles"),
            ("rolcreatedb", "can create databases"),
            ("rolreplication", "can start replication"),
            ("rolbypassrls", "bypasses row-level security"),
        ):
            if role[column]:
                findings.append(f"The login {text}.")

    for row in await conn.fetch(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY($1::text[]) "
        "AND pg_has_role(current_user, oid, 'USAGE') ORDER BY rolname",
        list(POWERFUL_ROLES),
    ):
        findings.append(f"The login belongs to the powerful role {row['rolname']}.")

    if await conn.fetchval(
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
    ):
        findings.append("The login can create schemas in this database.")
    for row in await conn.fetch(
        "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' "
        "AND nspname <> 'information_schema' "
        "AND has_schema_privilege(current_user, oid, 'CREATE') ORDER BY nspname LIMIT $1",
        MAX_FINDINGS,
    ):
        findings.append(f'The login can create objects in schema "{row["nspname"]}".')

    for row in await conn.fetch(
        "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p', 'f') AND n.nspname NOT LIKE 'pg\\_%' "
        "AND n.nspname <> 'information_schema' "
        "AND has_table_privilege(current_user, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') "
        "ORDER BY 1, 2 LIMIT $1",
        MAX_FINDINGS,
    ):
        findings.append(f'The login can change data in "{row["nspname"]}"."{row["relname"]}".')
    return findings[:MAX_FINDINGS]


async def check_connection(
    credentials: Credentials, *, connect_timeout: float, statement_timeout_seconds: float = 15
) -> ConnectionCheck:
    """Connect, read the server version, and check that the login can only read."""
    try:
        conn = await open_connection(
            credentials,
            connect_timeout=connect_timeout,
            statement_timeout_seconds=statement_timeout_seconds,
        )
    except Exception as exc:
        category, message = safe_error(exc, connect_timeout)
        logger.info("External database test failed", extra={"category": category})
        return ConnectionCheck(False, "failed", message)

    try:
        async with conn.transaction(readonly=True):
            version = str(await conn.fetchval("SHOW server_version"))[:120]
            findings = await role_findings(conn)
    except Exception as exc:
        category, message = safe_error(exc, connect_timeout)
        logger.info("External database test failed", extra={"category": category})
        return ConnectionCheck(False, "failed", message)
    finally:
        await conn.close(timeout=5)

    if findings:
        return ConnectionCheck(
            False,
            "unsafe",
            "Connected, but this login is not read-only, so it can't be used. "
            "Use a login that can only SELECT from the tables you want to analyse.",
            version,
            tuple(findings),
        )
    return ConnectionCheck(True, "ok", "Connected. The login is read-only.", version)
