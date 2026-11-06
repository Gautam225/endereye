"""Shared test fixtures.

Tests never touch real data. They use a separate database on the same server, with the same
login as DATABASE_URL: `eye_of_ender_test` (override the name with the TEST_POSTGRES_DB
environment variable). Tests marked `db` need it to exist; `scripts/setup_database.py`
creates it.
"""

import os

from app.core.config import get_settings, load_settings

TEST_DATABASE = os.environ.get("TEST_POSTGRES_DB", "eye_of_ender_test")

# Before the app is imported (importing it reads the settings): test mode, and the test
# database. Environment variables win over .env, so the app, Alembic, and every fixture
# below use the test database.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = (
    load_settings().sqlalchemy_url.set(database=TEST_DATABASE).render_as_string(hide_password=False)
)
get_settings.cache_clear()

import asyncio  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _require_test_database(settings: Settings) -> None:
    database = settings.sqlalchemy_url.database
    if database != TEST_DATABASE:
        pytest.exit(f"Refusing to run: tests would use database {database!r}, not the test one.")


@pytest.fixture(scope="session")
def settings() -> Settings:
    # Real LLM keys are never used in tests: no network calls, no quota spent.
    settings = load_settings(openrouter_api_keys=[], groq_api_keys=[])
    _require_test_database(settings)
    return settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def run_sql(settings: Settings, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    """Run one statement on the test database (from the test thread) and return the rows."""
    _require_test_database(settings)

    async def run() -> list[Any]:
        engine = create_async_engine(settings.sqlalchemy_url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params or {})
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture(scope="session")
def migrated_db() -> None:
    _require_test_database(get_settings())  # Alembic reads get_settings() too
    command.upgrade(Config(str(ALEMBIC_INI)), "head")


@pytest.fixture
def sql(settings: Settings) -> Callable[..., list[Any]]:
    """`sql("SELECT ...", {"param": 1})` on the test database."""
    return lambda statement, params=None: run_sql(settings, statement, params)


@pytest.fixture
def clean_db(settings: Settings, migrated_db: None) -> None:
    run_sql(settings, "TRUNCATE spaces, users, refresh_tokens, llm_calls RESTART IDENTITY CASCADE")
