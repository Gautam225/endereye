"""Checking a result before it is trusted: the AI sees the data's real date range, and a filtered
query that finds nothing gets one informed redo instead of a flat "no rows"."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

pytestmark = pytest.mark.db

WRONG_YEAR = (
    "SELECT region, sum(amount) AS revenue FROM sales WHERE order_date >= '2031-01-01' GROUP BY 1"
)
RIGHT = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
NO_FILTER_EMPTY = "SELECT region FROM sales LIMIT 0"


def run(api: TestClient, fake: FakeLLM) -> tuple[list, dict]:
    boss = admin(api)
    space_id = small_space(boss)
    use(api, fake)
    found = events(ask(boss, space_id, conversation(boss, space_id), "Revenue in 2031?"))
    return found, final(found)


def test_the_assistant_is_shown_how_far_the_data_runs(api: TestClient) -> None:
    fake = FakeLLM(chat_sql=[sql_plan(RIGHT)])

    run(api, fake)

    (prompt,) = fake.prompts("chat_sql")
    assert "order_date" in prompt and "[data runs from 2025-01-" in prompt


def test_a_filtered_query_that_finds_nothing_is_redone_once_with_the_real_ranges(
    api: TestClient,
) -> None:
    fake = FakeLLM(chat_sql=[sql_plan(WRONG_YEAR)], chat_repair=[sql_plan(RIGHT)])

    found, message = run(api, fake)

    assert message["attempts"] == 2 and message["row_count"] == 4 and message["sql"] == RIGHT
    (repair,) = fake.prompts("chat_repair")
    assert "ran but found nothing" in repair and "sales.order_date: 2025-" in repair
    notes = [d["text"] for n, d in found if n == "thought" and d["kind"] == "note"]
    assert any("checked against the data" in note for note in notes)


def test_a_second_empty_result_is_reported_as_it_is(api: TestClient) -> None:
    fake = FakeLLM(chat_sql=[sql_plan(WRONG_YEAR)], chat_repair=[sql_plan(WRONG_YEAR)])

    _, message = run(api, fake)

    assert message["status"] == "empty" and message["attempts"] == 3
    assert fake.purposes().count("chat_repair") == 2  # tried again, never in a loop


def test_an_empty_table_is_not_a_filter_problem(api: TestClient) -> None:
    fake = FakeLLM(chat_sql=[sql_plan(NO_FILTER_EMPTY)])

    _, message = run(api, fake)

    assert message["status"] == "empty" and "chat_repair" not in fake.purposes()


def test_a_sum_of_nothing_counts_as_nothing(api: TestClient) -> None:
    only_null = "SELECT sum(amount) AS revenue FROM sales WHERE region = 'Atlantis'"
    fake = FakeLLM(chat_sql=[sql_plan(only_null)], chat_repair=[sql_plan(RIGHT)])

    _, message = run(api, fake)

    assert message["attempts"] == 2 and message["row_count"] == 4
