"""An unknown table size is never shown as a number (no database needed).

A table of an external database that PostgreSQL has not analysed has no size estimate. It was
once shown as "0 rows", and the assistant took that as proof the table was empty."""

import pytest

from app.chat.prompts import ColumnContext, TableContext, _table_block, system_prompt
from app.core.rowcount import UNKNOWN, rows_text
from app.rag.cards import ColumnInfo, TableInfo, table_text


def test_a_size_is_written_only_when_it_is_known() -> None:
    assert rows_text(1) == "1 row"
    assert rows_text(1234) == "1,234 rows"
    assert rows_text(0) == "0 rows"  # a real, known empty table
    assert rows_text(22, approximate=True) == "about 22 rows"
    assert rows_text(UNKNOWN) is None
    assert rows_text(UNKNOWN, approximate=True) is None


@pytest.mark.parametrize(
    ("count", "approximate", "head"),
    [
        (3, False, "Table dietitians (3 rows)"),
        (22, True, "Table dietitians (about 22 rows)"),
        (UNKNOWN, True, "Table dietitians"),
    ],
)
def test_the_assistant_is_told_a_size_only_when_there_is_one(
    count: int, approximate: bool, head: str
) -> None:
    table = TableContext(
        "dietitians",
        "",
        count,
        (ColumnContext("id", "integer", "", (), ()),),
        approximate=approximate,
    )

    first = _table_block(table).splitlines()[0]

    assert first == head
    assert "0 rows" not in first or count == 0


def test_the_search_card_of_a_table_does_not_claim_a_size_either() -> None:
    column = (ColumnInfo("c1", "id", "integer", "", (), False, False, None),)
    unknown = TableInfo("t1", "dietitians", "People who advise", UNKNOWN, column)
    known = TableInfo("t1", "dietitians", "People who advise", 3, column)

    assert "rows" not in table_text(unknown, []) and "It has" not in table_text(unknown, [])
    assert "It has 3 rows." in table_text(known, [])


def test_the_assistant_is_told_not_to_decide_a_table_is_empty_from_a_size() -> None:
    for dialect in ("duckdb", "postgresql"):
        prompt = system_prompt(dialect)
        assert "Never conclude that a table is empty" in prompt
