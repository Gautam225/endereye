"""Health checks for PostgreSQL, the extensions Eye of Ender needs, and its tables."""

import asyncio
import time

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.migrations import expected_revision
from app.schemas.health import CheckResult

# check name -> PostgreSQL extension name
REQUIRED_EXTENSIONS = {"pgvector": "vector", "pg_trgm": "pg_trgm"}
CHECK_TIMEOUT_SECONDS = 5
MIGRATE_HINT = "In the backend folder run: alembic upgrade head"


def _describe(exc: Exception) -> str:
    """One readable line: the driver's own message, without SQLAlchemy's wrapper text."""
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        message = str(exc.orig)
    else:
        message = f"{type(exc).__name__}: {exc}".removesuffix(": ")
    lines = message.strip().splitlines()
    return lines[0] if lines else type(exc).__name__


async def check_database(engine: AsyncEngine, *, show_errors: bool) -> dict[str, CheckResult]:
    """Never raises: every failure becomes an "error" result."""
    started = time.perf_counter()
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as conn:
            server_version = await conn.scalar(text("SHOW server_version"))
            rows = await conn.execute(text("SELECT extname, extversion FROM pg_extension"))
            installed = {name: version for name, version in rows.all()}
            # to_regclass returns NULL instead of failing when the table doesn't exist.
            has_versions = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
            schema_version = (
                await conn.scalar(text("SELECT version_num FROM alembic_version"))
                if has_versions
                else None
            )
    except Exception as exc:
        detail = _describe(exc) if show_errors else "unreachable"
        unreachable = CheckResult(status="error", detail="database unreachable")
        return {
            "database": CheckResult(status="error", detail=detail),
            **{check: unreachable for check in REQUIRED_EXTENSIONS},
            "schema": unreachable,
        }

    checks = {
        "database": CheckResult(
            status="ok",
            version=server_version,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    }
    for check, extension in REQUIRED_EXTENSIONS.items():
        version = installed.get(extension)
        checks[check] = (
            CheckResult(status="ok", version=version)
            if version
            else CheckResult(
                status="error",
                detail="not installed - in the backend folder run: "
                "python scripts/setup_database.py "
                f"(or as 'postgres': CREATE EXTENSION {extension};)",
            )
        )
    checks["schema"] = _schema_check(schema_version)
    return checks


def _schema_check(current: str | None) -> CheckResult:
    expected = expected_revision()
    if current is None:
        return CheckResult(status="error", detail=f"Tables not created yet. {MIGRATE_HINT}")
    if expected is not None and current != expected:
        return CheckResult(
            status="error",
            version=current,
            detail=f"Tables are at version {current}, the code needs {expected}. {MIGRATE_HINT}",
        )
    return CheckResult(status="ok", version=current)
