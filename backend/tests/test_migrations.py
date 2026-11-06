import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


async def _fetch(settings: Settings, sql: str) -> list[str]:
    engine = create_async_engine(settings.sqlalchemy_url)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql))).scalars())
    finally:
        await engine.dispose()


@pytest.mark.db
def test_upgrade_to_head_is_repeatable(settings: Settings) -> None:
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # running twice must be a no-op

    assert asyncio.run(_fetch(settings, "SELECT version_num FROM alembic_version")) == ["0033"]
    extensions = asyncio.run(_fetch(settings, "SELECT extname FROM pg_extension"))
    assert {"vector", "pg_trgm"} <= set(extensions)
    tables = asyncio.run(_fetch(settings, "SELECT tablename FROM pg_tables"))
    assert {
        "llm_calls",
        "users",
        "refresh_tokens",
        "spaces",
        "space_members",
        "space_tables",
        "space_columns",
        "column_values",
        "space_joins",
        "knowledge_items",
        "documents",
        "chunks",
        "conversations",
        "messages",
        "sql_expressions",
    } <= set(tables)


@pytest.mark.db
def test_the_last_two_migrations_can_be_undone_and_redone(settings: Settings) -> None:
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    command.downgrade(config, "0007")
    tables = asyncio.run(_fetch(settings, "SELECT tablename FROM pg_tables"))
    columns = asyncio.run(
        _fetch(
            settings,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'messages'",
        )
    )
    assert "sql_expressions" not in tables and {"messages", "chunks"} <= set(tables)
    assert "feedback" not in columns and "seq" in columns
    command.upgrade(config, "head")
    assert "sql_expressions" in asyncio.run(_fetch(settings, "SELECT tablename FROM pg_tables"))
