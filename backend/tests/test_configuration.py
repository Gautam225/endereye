"""The space's configuration: About, SQL expressions, clarification rules, and their effect on
the prompt the AI is given (needs the test database)."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

pytestmark = pytest.mark.db

NET_REVENUE = "sum(amount) FILTER (WHERE status <> 'cancelled')"
SQL = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1"


def make_viewer(api: TestClient, boss: Any, space_id: str, email: str = "vera@example.com") -> Any:
    viewer = person(api, boss, email, "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    return viewer


def add_measure(boss: Any, space_id: str, **overrides: Any) -> Any:
    body = {
        "name": "Net revenue",
        "type": "measure",
        "expression": NET_REVENUE,
        "table_name": "sales",
        "description": "Revenue without cancelled orders",
        "synonyms": ["net sales"],
        **overrides,
    }
    return boss.post(f"/spaces/{space_id}/expressions", json=body)


def prompt_for(api: TestClient, boss: Any, space_id: str, question: str) -> str:
    fake = FakeLLM(chat_sql=[sql_plan(SQL)])
    use(api, fake)
    events(ask(boss, space_id, conversation(boss, space_id), question))
    (prompt,) = fake.prompts("chat_sql")
    return prompt


# ── About ────────────────────────────────────────────────────────────────────


def test_about_fields_are_saved_cleaned_and_limited(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    viewer = make_viewer(api, boss, space_id)

    created = boss.get(f"/spaces/{space_id}").json()
    assert (created["tags"], created["suggested_questions"]) == ([], [])
    assert created["owner_name"] == "Asha Admin"

    saved = boss.patch(
        f"/spaces/{space_id}",
        json={
            "tags": [" Sales ", "sales", "", "India"],
            "suggested_questions": ["  Revenue by region? ", "revenue by region?", "Top products?"],
        },
    ).json()
    assert saved["tags"] == ["Sales", "India"]
    assert saved["suggested_questions"] == ["Revenue by region?", "Top products?"]
    assert boss.patch(f"/spaces/{space_id}", json={"name": "Renamed"}).json()["tags"] == [
        "Sales",
        "India",
    ]
    assert viewer.get(f"/spaces/{space_id}").json()["tags"] == ["Sales", "India"]
    assert [s["tags"] for s in viewer.get("/spaces").json()] == [["Sales", "India"]]

    assert (
        boss.patch(f"/spaces/{space_id}", json={"tags": [f"t{i}" for i in range(11)]}).status_code
        == 422
    )
    assert boss.patch(f"/spaces/{space_id}", json={"tags": ["x" * 31]}).status_code == 422
    too_many = boss.patch(
        f"/spaces/{space_id}", json={"suggested_questions": [f"Question {i}?" for i in range(9)]}
    )
    assert too_many.status_code == 422
    assert viewer.patch(f"/spaces/{space_id}", json={"tags": ["x"]}).status_code == 403


def test_suggested_questions_start_with_the_ones_an_editor_wrote(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={
            "kind": "example_sql",
            "title": "Orders per region?",
            "body": "SELECT count(*) FROM sales",
        },
    )

    one = boss.patch(f"/spaces/{space_id}", json={"suggested_questions": ["How is revenue doing?"]})
    assert one.status_code == 200
    assert boss.get(f"/spaces/{space_id}/suggestions").json() == [
        "What data is available for me to explore?",
        "How is revenue doing?",
        "Orders per region?",
    ]

    boss.patch(f"/spaces/{space_id}", json={"suggested_questions": ["First?", "Second?", "Third?"]})
    assert boss.get(f"/spaces/{space_id}/suggestions").json() == [
        "First?",
        "Second?",
        "Third?",
        "Orders per region?",
    ]


# ── SQL expressions ──────────────────────────────────────────────────────────


def test_expressions_are_tested_on_their_table_before_they_are_saved(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)

    measure = add_measure(boss, space_id)
    large = add_measure(
        boss,
        space_id,
        name="Large orders",
        type="filter",
        expression="amount > 5000",
        is_default=False,
    )
    month = add_measure(
        boss,
        space_id,
        name="Order month",
        type="dimension",
        expression="date_trunc('month', order_date)",
        synonyms=[],
    )

    assert [r.status_code for r in (measure, large, month)] == [201, 201, 201]
    assert measure.json()["synonyms"] == ["net sales"]
    listed = boss.get(f"/spaces/{space_id}/expressions").json()
    assert [(e["type"], e["name"]) for e in listed] == [
        ("dimension", "Order month"),
        ("filter", "Large orders"),
        ("measure", "Net revenue"),
    ]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"expression": "sum(revenue)"}, "doesn't work on sales"),  # no such column
        ({"expression": "amount >"}, "doesn't work on sales"),  # not valid SQL
        ({"expression": "amount; DROP TABLE sales"}, "doesn't work on sales"),  # a second statement
        ({"expression": "(SELECT count(*) FROM read_csv('/etc/passwd'))"}, "not allowed"),
        ({"expression": "(SELECT count(*) FROM customers)"}, "no table called"),
        ({"table_name": "nowhere"}, "no table called 'nowhere'"),
        (
            {"type": "filter", "expression": "sum(amount)"},
            "doesn't work on sales",
        ),  # not true/false
    ],
    ids=["column", "syntax", "second-statement", "file-read", "other-table", "table", "filter-sum"],
)
def test_expressions_that_do_not_work_or_are_not_safe_are_refused(
    api: TestClient, changes: dict[str, Any], reason: str
) -> None:
    boss = admin(api)
    space_id = small_space(boss)

    response = add_measure(boss, space_id, **changes)

    assert (response.status_code, code(response)) == (400, "invalid_expression")
    assert reason in response.json()["error"]["message"]
    assert boss.get(f"/spaces/{space_id}/expressions").json() == []  # nothing was stored


def test_expression_rules_names_and_access(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    viewer = make_viewer(api, boss, space_id)
    first = add_measure(boss, space_id).json()
    base = f"/spaces/{space_id}/expressions"

    assert add_measure(boss, space_id).status_code == 409  # the name is taken
    default_measure = add_measure(boss, space_id, name="Other", is_default=True)
    assert default_measure.status_code == 422  # only filters can be default
    assert add_measure(boss, space_id, name="").status_code == 422
    not_a_filter = boss.patch(
        f"{base}/{first['id']}", json={"type": "dimension", "is_default": True}
    )
    assert (not_a_filter.status_code, code(not_a_filter)) == (400, "validation_error")

    updated = boss.patch(f"{base}/{first['id']}", json={"description": "New text"})
    assert updated.json()["description"] == "New text"
    broken = boss.patch(f"{base}/{first['id']}", json={"expression": "sum(nope)"})
    assert (broken.status_code, code(broken)) == (400, "invalid_expression")
    assert boss.get(base).json()[0]["expression"] == NET_REVENUE  # a bad edit changes nothing

    assert viewer.get(base).status_code == 200
    assert (
        viewer.post(base, json={"name": "X", "type": "measure", "expression": "1"}).status_code
        == 403
    )
    assert viewer.patch(f"{base}/{first['id']}", json={"description": "x"}).status_code == 403
    assert viewer.delete(f"{base}/{first['id']}").status_code == 403
    assert boss.delete(f"{base}/{first['id']}").status_code == 204
    assert boss.delete(f"{base}/{first['id']}").status_code == 404


# ── Clarification rules ──────────────────────────────────────────────────────


def test_clarification_rules_are_knowledge_items_with_a_trigger_and_a_question(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    url = f"/spaces/{space_id}/knowledge"

    assert (
        boss.post(url, json={"kind": "clarification", "body": "Which period?"}).status_code == 422
    )
    assert (
        boss.post(url, json={"kind": "clarification", "title": "sales are asked about"}).status_code
        == 422
    )
    assert (
        boss.post(
            url,
            json={"kind": "clarification", "title": "x", "body": "y", "trusted": True},
        ).status_code
        == 422
    )
    made = boss.post(
        url,
        json={
            "kind": "clarification",
            "title": "the user asks about sales without a time period",
            "body": "Which period do you mean: this month, this quarter or this year?",
        },
    )

    assert made.status_code == 201
    assert boss.get(url, params={"kind": "clarification"}).json()[0]["id"] == made.json()["id"]
    assert boss.get(f"/spaces/{space_id}/index").json()["chunks"]["clarification"] == 1
    emptied = boss.patch(f"{url}/{made.json()['id']}", json={"title": ""})
    assert (emptied.status_code, code(emptied)) == (400, "validation_error")


# ── Configuration changes what the AI is told ────────────────────────────────


def test_changing_the_configuration_changes_the_prompt(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    base = f"/spaces/{space_id}"
    plain = prompt_for(api, boss, space_id, "What was net revenue by region?")
    assert "Business definitions" not in plain and "Default filters" not in plain
    assert "When to ask a clarifying question" not in plain

    measure = add_measure(boss, space_id).json()
    boss.post(
        f"{base}/expressions",
        json={
            "name": "Not cancelled",
            "type": "filter",
            "expression": "status <> 'cancelled'",
            "table_name": "sales",
            "description": "Cancelled orders never count",
            "is_default": True,
        },
    )
    boss.post(
        f"{base}/knowledge",
        json={
            "kind": "clarification",
            "title": "the user asks about sales without a time period",
            "body": "Which period do you mean?",
        },
    )
    configured = prompt_for(api, boss, space_id, "What was net revenue by region?")

    assert "## Business definitions (use these exact SQL expressions)" in configured
    assert f'Measure "Net revenue" on table sales: {NET_REVENUE}' in configured
    assert "## Default filters" in configured and "sales: status <> 'cancelled'" in configured
    assert "Cancelled orders never count" in configured
    assert (
        "- When the user asks about sales without a time period: ask Which period do you mean?"
        in configured
    )
    # A default filter is always included; it does not depend on the question.
    unrelated = prompt_for(api, boss, space_id, "List the products")
    assert "sales: status <> 'cancelled'" in unrelated

    boss.patch(f"{base}/expressions/{measure['id']}", json={"expression": "sum(amount)"})
    edited = prompt_for(api, boss, space_id, "What was net revenue by region?")
    assert 'Measure "Net revenue" on table sales: sum(amount)' in edited
    assert NET_REVENUE not in edited

    boss.delete(f"{base}/expressions/{measure['id']}")
    removed = prompt_for(api, boss, space_id, "What was net revenue by region?")
    assert "Net revenue" not in removed and "sales: status <> 'cancelled'" in removed


def test_a_definition_is_found_by_its_synonym(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    add_measure(
        boss, space_id, name="Gross merchandise value", synonyms=["GMV"], expression="sum(amount)"
    )

    prompt = prompt_for(api, boss, space_id, "What was the GMV in the south?")

    assert 'Measure "Gross merchandise value" on table sales: sum(amount)' in prompt
    chunks = boss.get(f"/spaces/{space_id}/index").json()["chunks"]
    assert chunks["expression"] == 1


def test_a_generated_query_can_use_a_definition_and_the_answer_is_checked_like_any_other(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    add_measure(boss, space_id)
    fake = FakeLLM(
        chat_sql=[sql_plan(f"SELECT region, {NET_REVENUE} AS net_revenue FROM sales GROUP BY 1")]
    )
    use(api, fake)

    message = final(
        events(ask(boss, space_id, conversation(boss, space_id), "Net revenue by region"))
    )

    assert message["status"] == "ok" and NET_REVENUE in message["sql"]
