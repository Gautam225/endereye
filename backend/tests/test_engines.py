"""Choosing and narrowing the SQL engine of a space (no database needed)."""

import pytest

from app.core.config import Settings
from app.engine.pg_sql_guard import AllowedTable
from app.engine.sql_guard import SqlNotAllowedError
from app.services.engines import PostgresEngine

TABLES = [
    AllowedTable("orders", "public", "orders", {"id": "integer"}),
    AllowedTable("people", "public", "people", {"id": "integer"}),
]


def test_the_assistant_can_only_use_the_tables_it_was_shown(settings: Settings) -> None:
    engine = PostgresEngine(None, TABLES, settings)  # type: ignore[arg-type]

    assert '"orders"' in engine.check("SELECT id FROM orders", {"orders"}).run
    with pytest.raises(SqlNotAllowedError, match="no table called 'people'"):
        engine.check("SELECT id FROM people", {"orders"})
    # a person editing SQL by hand may use every table of the space
    assert '"people"' in engine.check("SELECT id FROM people").run


def test_the_displayed_sql_is_the_one_written_and_the_run_sql_is_rewritten(
    settings: Settings,
) -> None:
    engine = PostgresEngine(None, TABLES, settings)  # type: ignore[arg-type]

    checked = engine.check("SELECT id FROM orders;")

    assert checked.display == "SELECT id FROM orders"
    assert checked.run != checked.display and '"public"."orders"' in checked.run
