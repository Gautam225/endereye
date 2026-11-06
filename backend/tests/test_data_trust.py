"""What the assistant is told is true must be confirmed: joins an editor has confirmed, and example
SQL that really runs on the space's data (needs the test database)."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, sql_plan, use
from test_metadata import CUSTOMERS_CSV, ORDERS_CSV
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

pytestmark = pytest.mark.db

QUESTION = "How many orders does each customer have?"
SQL = "SELECT customer_id, count(*) AS orders FROM orders GROUP BY 1"


def two_tables(boss: TestClient) -> str:
    space_id = new_space(boss)
    assert boss.upload(space_id, "orders.csv", ORDERS_CSV).status_code == 201
    assert boss.upload(space_id, "customers.csv", CUSTOMERS_CSV).status_code == 201
    return space_id


def joins_in_prompt(api: TestClient, boss: TestClient, space_id: str) -> str:
    llm = FakeLLM(chat_sql=[sql_plan(SQL)])
    use(api, llm)
    final(events(ask(boss, space_id, conversation(boss, space_id), QUESTION)))
    return llm.prompts("chat_sql")[0]


def test_a_join_that_was_only_guessed_is_not_given_to_the_model_until_confirmed(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = two_tables(boss)
    (join,) = boss.post(f"/spaces/{space_id}/joins/detect").json()
    assert join["confirmed"] is False

    assert "## Joins" not in joins_in_prompt(api, boss, space_id)

    boss.patch(f"/spaces/{space_id}/joins/{join['id']}", json={"confirmed": True})

    assert "orders.customer_id = customers.id" in joins_in_prompt(api, boss, space_id)


def test_example_sql_must_run_on_the_spaces_data_not_just_parse(api: TestClient) -> None:
    boss = admin(api)
    space_id = two_tables(boss)
    base = {"kind": "example_sql", "title": "Orders per customer", "body": SQL}

    saved = boss.post(f"/spaces/{space_id}/knowledge", json=base)
    missing = boss.post(
        f"/spaces/{space_id}/knowledge",
        json={**base, "body": "SELECT nope FROM orders"},
    )
    edited = boss.patch(
        f"/spaces/{space_id}/knowledge/{saved.json()['id']}",
        json={"body": "SELECT nope FROM orders"},
    )

    assert saved.status_code == 201
    assert (missing.status_code, code(missing)) == (400, "validation_error")
    assert "does not run" in missing.json()["error"]["message"]
    assert (edited.status_code, code(edited)) == (400, "validation_error")
