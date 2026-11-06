"""Turn "the database is down or misconfigured" and "the tables are missing" into a clear
503 that says how to fix it, instead of a generic 500.

What the driver raises (checked against PostgreSQL 18 + asyncpg):
- wrong user/password -> DBAPIError whose `orig.sqlstate` is 28P01 (28xxx = login problems)
- database missing    -> DBAPIError, sqlstate 3D000
- table missing       -> ProgrammingError, sqlstate 42P01
- server not running  -> a plain ConnectionRefusedError/OSError from inside asyncpg (not wrapped)
"""

import logging
import socket
from dataclasses import dataclass
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import error_response, handle_unexpected_error

logger = logging.getLogger(__name__)

# Undefined table / column / function: the code is newer than the database.
SCHEMA_SQLSTATES = frozenset({"42P01", "42703", "42883"})
# Bad login (28xxx), no such database, connection failures (08xxx), server shutting
# down or starting up (57Pxx), too many connections (53300).
UNAVAILABLE_PREFIXES = ("28", "08", "57P", "53300", "3D000")

SETUP_HINT = "run `python scripts/setup_database.py` in the backend folder"


@dataclass(frozen=True, slots=True)
class DatabaseProblem:
    kind: Literal["unavailable", "not_ready"]
    reason: str  # one line, for developers


def find_database_problem(exc: BaseException, settings: Settings) -> DatabaseProblem | None:
    """Recognise database connection and schema problems anywhere in the exception chain."""
    for error in _chain(exc):
        sqlstate = getattr(error, "sqlstate", None)
        if isinstance(sqlstate, str):
            if sqlstate in SCHEMA_SQLSTATES:
                return DatabaseProblem("not_ready", _first_line(error))
            if sqlstate.startswith(UNAVAILABLE_PREFIXES):
                return DatabaseProblem("unavailable", _first_line(error))
        if isinstance(error, OSError) and _raised_by_driver(error):
            return DatabaseProblem("unavailable", _describe_os_error(error, settings))
    return None


def register_database_error_handlers(app: FastAPI) -> None:
    # Registered for these exception types (not just `Exception`), so a known database
    # problem is answered here and not re-raised as a crash with a traceback.
    app.add_exception_handler(SQLAlchemyError, _handle)
    app.add_exception_handler(OSError, _handle)


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    settings: Settings = request.app.state.settings
    problem = find_database_problem(exc, settings)
    if problem is None:
        return await handle_unexpected_error(request, exc)

    logger.warning(
        "Database %s: %s",
        "unavailable" if problem.kind == "unavailable" else "tables missing or out of date",
        problem.reason,
    )
    details = None if settings.is_production else {"reason": problem.reason}
    if problem.kind == "unavailable":
        code = "database_unavailable"
        message = (
            "The database is not reachable right now. Please try again in a moment."
            if settings.is_production
            else f"Can't connect to the database: {problem.reason} To fix it, {SETUP_HINT} "
            "(or correct DATABASE_URL in .env), then restart the backend."
        )
    else:
        code = "database_not_ready"
        message = (
            "The service is being updated. Please try again in a moment."
            if settings.is_production
            else "The database tables are missing or out of date. "
            "In the backend folder run: alembic upgrade head"
        )
    return error_response(request, 503, code, message, details, {"Retry-After": "5"})


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception, plus what it wraps (`orig`) and what caused it, without repeats."""
    seen: list[BaseException] = []
    pending: list[BaseException | None] = [exc]
    while pending and len(seen) < 20:
        error = pending.pop(0)
        if error is None or any(error is s for s in seen):
            continue
        seen.append(error)
        pending.extend([getattr(error, "orig", None), error.__cause__, error.__context__])
    return seen


def _raised_by_driver(error: BaseException) -> bool:
    """True when the error came out of the database driver (not, say, a file operation)."""
    tb = error.__traceback__
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "")
        if module.startswith(("asyncpg", "sqlalchemy")):
            return True
        tb = tb.tb_next
    return False


def _describe_os_error(error: OSError, settings: Settings) -> str:
    url = settings.sqlalchemy_url
    host = url.host or "localhost"
    where = f"{host}:{url.port or 5432}"
    if isinstance(error, TimeoutError):
        return f"the database at {where} did not answer in time."
    if isinstance(error, socket.gaierror):
        return f"the database host '{host}' could not be found."
    return f"nothing is accepting connections at {where}. Is the PostgreSQL service running?"


def _first_line(error: BaseException) -> str:
    lines = str(error).strip().splitlines()
    text = lines[0] if lines else type(error).__name__
    return text if text.endswith(".") else f"{text}."
