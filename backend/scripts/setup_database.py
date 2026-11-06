"""Set up PostgreSQL for Eye of Ender in one step.

From the backend folder, with .venv active (PowerShell or the VS Code terminal):

    python scripts/setup_database.py

You type the PostgreSQL superuser password once: the one chosen when PostgreSQL was
installed (pgAdmin asks for the same one). It is never shown or saved. (If DATABASE_URL in
.env already logs in as that superuser, that password is used and you aren't asked.)
Then this script:

  1. creates the app's own login (eoe_app), or gives it a new password,
  2. creates the app database and the test database, owned by that login,
  3. installs the pgvector and pg_trgm extensions in both, and hands any existing tables
     to the app login (for example tables created earlier while connected as 'postgres'),
  4. writes DATABASE_URL into .env (replacing old POSTGRES_* lines; nothing else changes),
  5. creates the tables (alembic upgrade head) and checks the result.

Safe to run again. See all options with --help.
"""

import argparse
import asyncio
import getpass
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import asyncpg  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from sqlalchemy import URL, make_url  # noqa: E402
from sqlalchemy.exc import ArgumentError  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import ENV_FILE  # noqa: E402
from app.services.health import check_database  # noqa: E402

# For automation only; normally you are asked and the password is never stored.
PASSWORD_ENV = "EOE_SUPERUSER_PASSWORD"
# Simple lowercase names only, so they are safe to put into SQL as identifiers.
SIMPLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
# The old way to configure the database; DATABASE_URL replaces these lines.
OLD_DATABASE_KEYS = tuple(f"POSTGRES_{part}" for part in ("HOST", "PORT", "DB", "USER", "PASSWORD"))


class SetupError(Exception):
    """A problem with a known fix. Printed as a message, without a traceback."""


def update_env_text(text: str, updates: dict[str, str], remove: tuple[str, ...] = ()) -> str:
    """Set KEY=value lines in .env content and drop the `remove` keys.

    Every other line (comments included) stays exactly as it was. A new key goes where the
    first removed line was, or at the end of the file.
    """
    out: list[str] = []
    found: set[str] = set()
    insert_at: int | None = None
    for line in text.splitlines():
        key = None
        if not line.lstrip().startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            found.add(key)
        elif key in remove:
            if insert_at is None:
                insert_at = len(out)
        else:
            out.append(line)
    missing = [f"{key}={updates[key]}" for key in updates if key not in found]
    if missing and insert_at is not None:
        out[insert_at:insert_at] = missing
    elif missing:
        out.extend(["", *missing])
    newline = "\r\n" if "\r\n" in text else "\n"
    return newline.join(out) + newline


def database_url(args: argparse.Namespace, password: str) -> str:
    """The DATABASE_URL value for the app login. Special characters are URL-encoded."""
    url = URL.create(
        "postgresql",
        username=args.app_user,
        password=password,
        host=args.host,
        port=args.port,
        database=args.database,
    )
    return url.render_as_string(hide_password=False)


def current_url(values: dict[str, str]) -> URL | None:
    """DATABASE_URL from the .env values, if it is there and readable."""
    raw = values.get("DATABASE_URL")
    if not raw:
        return None
    try:
        return make_url(raw.strip())
    except (ArgumentError, ValueError):
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # Read --env-file first, because the other defaults come from that file.
    first = argparse.ArgumentParser(add_help=False)
    first.add_argument("--env-file", type=Path, default=ENV_FILE)
    env_file = first.parse_known_args(argv)[0].env_file
    current = {k: v for k, v in dotenv_values(env_file).items() if v} if env_file.exists() else {}
    url = current_url(current)

    parser = argparse.ArgumentParser(
        description="Set up PostgreSQL for Eye of Ender: login, databases, extensions, tables.",
        parents=[first],
    )
    parser.add_argument(
        "--host", default=(url and url.host) or current.get("POSTGRES_HOST", "localhost")
    )
    parser.add_argument(
        "--port",
        type=int,
        default=(url and url.port) or int(current.get("POSTGRES_PORT", "5432")),
    )
    parser.add_argument(
        "--superuser", default="postgres", help="PostgreSQL superuser (default: postgres)"
    )
    parser.add_argument(
        "--database",
        default=(url and url.database) or current.get("POSTGRES_DB") or "eye_of_ender",
    )
    parser.add_argument("--test-database", default="eye_of_ender_test")
    parser.add_argument("--app-user", default="eoe_app")
    parser.add_argument("--yes", action="store_true", help="don't ask before making changes")
    args = parser.parse_args(argv)
    # If DATABASE_URL already logs in as the superuser, its password can be reused.
    args.known_superuser_password = (
        url.password if url is not None and url.username == args.superuser else None
    )
    for option in ("database", "test_database", "app_user"):
        value = getattr(args, option)
        if not SIMPLE_NAME.fullmatch(value):
            raise SetupError(
                f"'{value}' is not a simple name. Use lowercase letters, digits and "
                f"underscores, e.g. --{option.replace('_', '-')} eye_of_ender"
            )
    return args


def say(message: str) -> None:
    print(f"  [ok] {message}")


async def connect(args: argparse.Namespace, user: str, password: str, database: str):
    try:
        return await asyncpg.connect(
            host=args.host,
            port=args.port,
            user=user,
            password=password,
            database=database,
            timeout=10,
        )
    except asyncpg.InvalidPasswordError:
        raise SetupError(
            f"PostgreSQL rejected the password for '{user}'. Use the password chosen when "
            "PostgreSQL was installed (pgAdmin asks for the same one when you open the server)."
        ) from None
    except asyncpg.InvalidAuthorizationSpecificationError:
        raise SetupError(
            f"PostgreSQL has no login called '{user}'. Pass the right one with --superuser NAME."
        ) from None
    except (OSError, TimeoutError):
        raise SetupError(
            f"Nothing is answering at {args.host}:{args.port}. Is PostgreSQL running? On "
            "Windows: press Win+R, type services.msc, and start 'postgresql-x64-18'."
        ) from None


async def prepare_server(args: argparse.Namespace, superuser_password: str) -> str:
    """Create or update the login and databases. Returns the app login's new password."""
    role = f'"{args.app_user}"'
    admin = await connect(args, args.superuser, superuser_password, "postgres")
    try:
        if not await admin.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"):
            raise SetupError(f"'{args.superuser}' is not a superuser. Use --superuser postgres.")
        if not await admin.fetchval("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"):
            raise SetupError(
                "The pgvector extension is not installed on this PostgreSQL server. "
                "Install it first: https://github.com/pgvector/pgvector#windows"
            )

        # URL-safe random characters only, so it can be written into the SQL as-is.
        app_password = secrets.token_urlsafe(24)
        if await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", args.app_user):
            await admin.execute(f"ALTER ROLE {role} WITH LOGIN PASSWORD '{app_password}'")
            say(f"Login '{args.app_user}' already existed: gave it a new password")
        else:
            await admin.execute(
                f"CREATE ROLE {role} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                f"PASSWORD '{app_password}'"
            )
            say(f"Login '{args.app_user}' created")

        for database in (args.database, args.test_database):
            owner = await admin.fetchval(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = $1", database
            )
            if owner is None:
                await admin.execute(f'CREATE DATABASE "{database}" OWNER {role}')
                say(f"Database '{database}' created")
            elif owner != args.app_user:
                await admin.execute(f'ALTER DATABASE "{database}" OWNER TO {role}')
                say(f"Database '{database}' already existed: now owned by '{args.app_user}'")
            else:
                say(f"Database '{database}' already set up")
    finally:
        await admin.close()

    for database in (args.database, args.test_database):
        conn = await connect(args, args.superuser, superuser_password, database)
        try:
            await conn.execute(
                "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
            )
            say(f"Extensions pgvector and pg_trgm ready in '{database}'")
            moved = await take_over_tables(conn, args.app_user)
        finally:
            await conn.close()
        if moved:
            say(f"Handed {moved} existing table(s) in '{database}' to '{args.app_user}'")

    check = await connect(args, args.app_user, app_password, args.database)
    await check.close()
    say(f"Login '{args.app_user}' can connect to '{args.database}'")
    return app_password


# Tables, views, materialized views, sequences, and foreign tables in the public schema
# that someone else owns. Left out: extension objects, and sequences that belong to a table
# (they move along with their table).
FOREIGN_OBJECTS = """
SELECT c.relname, c.relkind::text AS relkind  -- "char" would arrive as bytes without the cast
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  AND pg_get_userbyid(c.relowner) <> $1
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('e', 'a', 'i')
  )
ORDER BY c.relkind DESC, c.relname
"""

ALTER_KIND = {
    "r": "TABLE",
    "p": "TABLE",
    "f": "FOREIGN TABLE",
    "v": "VIEW",
    "m": "MATERIALIZED VIEW",
    "S": "SEQUENCE",
}


async def take_over_tables(conn: asyncpg.Connection, app_user: str) -> int:
    """Give the app login ownership of the app's tables, e.g. ones created earlier while
    connected as 'postgres'. Without this, the app login could not read them. Returns how
    many objects changed owner."""
    rows = await conn.fetch(FOREIGN_OBJECTS, app_user)
    for row in rows:
        name = '"' + row["relname"].replace('"', '""') + '"'
        await conn.execute(
            f'ALTER {ALTER_KIND[row["relkind"]]} public.{name} OWNER TO "{app_user}"'
        )
    return len(rows)


def create_tables(args: argparse.Namespace, app_password: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url(args, app_password)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-8:])
        raise SetupError(f"Creating the tables failed:\n{tail}")
    say("Tables created and up to date (alembic upgrade head)")


async def verify(args: argparse.Namespace, app_password: str) -> bool:
    url = URL.create(
        "postgresql+asyncpg",
        username=args.app_user,
        password=app_password,
        host=args.host,
        port=args.port,
        database=args.database,
    )
    engine = create_async_engine(url)
    try:
        checks = await check_database(engine, show_errors=True)
    finally:
        await engine.dispose()
    healthy = True
    for name, check in checks.items():
        if check.status == "ok":
            say(f"Health check {name}: ok{f' ({check.version})' if check.version else ''}")
        else:
            healthy = False
            print(f"  [!!] Health check {name}: {check.detail}")
    return healthy


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("Eye of Ender database setup\n")
    print(f"  PostgreSQL server : {args.host}:{args.port}")
    print(f"  App database      : {args.database}  (test database: {args.test_database})")
    print(f"  App login         : {args.app_user}  (gets a new random password)")
    print(f"  Settings file     : {args.env_file}\n")

    if not args.yes:
        answer = input("Set this up now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Nothing was changed.")
            return 1

    password = os.environ.get(PASSWORD_ENV) or args.known_superuser_password
    if password and not os.environ.get(PASSWORD_ENV):
        print(f"Using the password for '{args.superuser}' from DATABASE_URL in .env.")
    if not password:
        password = getpass.getpass(
            f"Password for PostgreSQL user '{args.superuser}' (typing stays hidden): "
        )
    if not password:
        raise SetupError("No password was entered. Nothing was changed.")

    print()
    app_password = asyncio.run(prepare_server(args, password))

    text = args.env_file.read_bytes().decode("utf-8") if args.env_file.exists() else ""
    updates = {"DATABASE_URL": database_url(args, app_password)}
    args.env_file.write_bytes(update_env_text(text, updates, OLD_DATABASE_KEYS).encode("utf-8"))
    say(f"Saved DATABASE_URL in {args.env_file.name} (password not shown)")

    create_tables(args, app_password)
    healthy = asyncio.run(verify(args, app_password))

    if not healthy:
        print("\nSome checks failed; see the lines marked [!!] above.")
        return 1
    print(
        "\nAll set. Now restart the backend (it reads .env only when it starts):\n"
        "  press Ctrl+C where it runs, then: uvicorn app.main:app --reload\n"
        "Then open http://localhost:5173. The first visit asks you to create the admin account."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as error:
        print(f"\nSetup stopped: {error}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
