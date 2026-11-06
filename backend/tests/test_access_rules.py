"""What each person may read: hidden and masked columns and row filters, applied where data is
read, so they hold for the assistant, the SQL tab and previews alike."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

pytestmark = pytest.mark.db


def table_id(boss: Any, space_id: str) -> str:
    return boss.get(f"/spaces/{space_id}/tables").json()[0]["id"]


def rule(boss: Any, space_id: str, **body: Any) -> Any:
    return boss.post(f"/spaces/{space_id}/access-rules", json=body)


def setup(api: TestClient) -> tuple[Any, Any, Any, str, str]:
    boss = admin(api)
    space_id = small_space(boss)
    viewer = person(api, boss, "vera@example.com", "viewer")
    editor = person(api, boss, "ed@example.com", "editor")
    assert (
        boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"}).status_code
        == 200
    )
    assert (
        boss.put(f"/spaces/{space_id}/members/{editor.id}", json={"role": "editor"}).status_code
        == 200
    )
    return boss, viewer, editor, space_id, table_id(boss, space_id)


def preview(who: Any, space_id: str, tid: str) -> dict:
    response = who.get(f"/spaces/{space_id}/tables/{tid}/preview")
    assert response.status_code == 200, response.text
    return response.json()


def sql(who: Any, space_id: str, text: str) -> Any:
    return who.post(f"/spaces/{space_id}/query", json={"sql": text})


# ── Columns ──────────────────────────────────────────────────────────────────


def test_a_hidden_column_does_not_exist_for_the_people_the_rule_names(api: TestClient) -> None:
    boss, viewer, editor, space_id, tid = setup(api)
    assert (
        rule(
            boss,
            space_id,
            table_id=tid,
            kind="hide_column",
            column="unit_price",
            audience="viewers",
        ).status_code
        == 201
    )

    seen_by_viewer = [c["name"] for c in preview(viewer, space_id, tid)["columns"]]
    seen_by_editor = [c["name"] for c in preview(editor, space_id, tid)["columns"]]
    seen_by_admin = [c["name"] for c in preview(boss, space_id, tid)["columns"]]

    assert "unit_price" not in seen_by_viewer and "amount" in seen_by_viewer  # SELECT * too
    assert "unit_price" in seen_by_editor and "unit_price" in seen_by_admin  # not their rule


def test_a_hidden_column_can_not_be_reached_by_name_either(api: TestClient) -> None:
    boss, _, editor, space_id, tid = setup(api)
    rule(boss, space_id, table_id=tid, kind="hide_column", column="unit_price", audience="members")

    direct = sql(editor, space_id, "SELECT unit_price FROM sales")
    sneaky = sql(editor, space_id, "SELECT * FROM sales WHERE unit_price > 0")
    fine = sql(editor, space_id, "SELECT sum(amount) AS total FROM sales")

    assert direct.status_code == 400 and sneaky.status_code == 400
    assert fine.status_code == 200
    assert sql(boss, space_id, "SELECT sum(unit_price) AS p FROM sales").status_code == 200


def test_a_masked_column_is_there_but_empty(api: TestClient) -> None:
    boss, viewer, _, space_id, tid = setup(api)
    rule(boss, space_id, table_id=tid, kind="mask_column", column="customer_id", audience="viewers")

    shown = preview(viewer, space_id, tid)
    names = [c["name"] for c in shown["columns"]]
    column = names.index("customer_id")

    assert all(row[column] is None for row in shown["rows"])
    assert any(row[names.index("amount")] is not None for row in shown["rows"])
    full = preview(boss, space_id, tid)
    assert any(row[names.index("customer_id")] is not None for row in full["rows"])


# ── Rows ─────────────────────────────────────────────────────────────────────


def test_a_row_filter_leaves_only_the_rows_a_person_may_see(api: TestClient) -> None:
    boss, _, editor, space_id, tid = setup(api)
    everything = sql(boss, space_id, "SELECT count(*) AS n FROM sales").json()["rows"][0][0]
    made = rule(
        boss,
        space_id,
        table_id=tid,
        kind="row_filter",
        expression="region = 'East'",
        audience="members",
    )
    assert made.status_code == 201

    regions = sql(editor, space_id, "SELECT DISTINCT region FROM sales").json()["rows"]
    count = sql(editor, space_id, "SELECT count(*) AS n FROM sales").json()["rows"][0][0]

    assert regions == [["East"]] and 0 < count < everything
    assert sql(boss, space_id, "SELECT count(*) AS n FROM sales").json()["rows"][0][0] == everything


def test_a_filter_holds_in_joins_ctes_and_subqueries(api: TestClient) -> None:
    boss, _, editor, space_id, tid = setup(api)
    rule(
        boss,
        space_id,
        table_id=tid,
        kind="row_filter",
        expression="region = 'East'",
        audience="members",
    )

    queries = [
        "WITH s AS (SELECT * FROM sales) SELECT DISTINCT region FROM s",
        "SELECT DISTINCT a.region FROM sales a JOIN sales b ON a.order_id = b.order_id",
        "SELECT DISTINCT region FROM (SELECT * FROM sales) t",
        "SELECT region FROM sales UNION ALL SELECT region FROM sales",
    ]
    for text in queries:
        found = sql(editor, space_id, text)
        assert found.status_code == 200, text
        assert {r[0] for r in found.json()["rows"]} == {"East"}, text


def test_several_filters_all_apply_and_a_named_person_is_held_to_them_whatever_their_role(
    api: TestClient,
) -> None:
    boss, _, editor, space_id, tid = setup(api)
    rule(
        boss,
        space_id,
        table_id=tid,
        kind="row_filter",
        expression="region = 'East'",
        audience="viewers",
        user_id=editor.id,
    )
    rule(
        boss,
        space_id,
        table_id=tid,
        kind="row_filter",
        expression="amount > 0",
        audience="viewers",
        user_id=editor.id,
    )

    shown = sql(editor, space_id, "SELECT DISTINCT region FROM sales").json()["rows"]

    assert shown == [["East"]]


# ── The assistant ────────────────────────────────────────────────────────────


def test_the_assistant_works_inside_the_same_limits_and_is_not_told_what_is_hidden(
    api: TestClient,
) -> None:
    boss, viewer, _, space_id, tid = setup(api)
    rule(boss, space_id, table_id=tid, kind="hide_column", column="unit_price", audience="viewers")
    rule(
        boss,
        space_id,
        table_id=tid,
        kind="row_filter",
        expression="region = 'East'",
        audience="viewers",
    )
    fake = FakeLLM(
        chat_sql=[sql_plan("SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1")]
    )
    use(api, fake)

    message = final(
        events(ask(viewer, space_id, conversation(viewer, space_id), "Revenue by region"))
    )

    assert [row[0] for row in message["rows"]] == ["East"]  # the only region this person has
    (prompt,) = fake.prompts("chat_sql")
    assert "amount" in prompt and "unit_price" not in prompt


def test_asking_for_a_hidden_column_fails_and_is_sent_back_for_a_fix(api: TestClient) -> None:
    boss, viewer, _, space_id, tid = setup(api)
    rule(boss, space_id, table_id=tid, kind="hide_column", column="unit_price", audience="viewers")
    fake = FakeLLM(
        chat_sql=[sql_plan("SELECT avg(unit_price) AS p FROM sales")],
        chat_repair=[sql_plan("SELECT avg(amount) AS p FROM sales")],
    )
    use(api, fake)

    message = final(events(ask(viewer, space_id, conversation(viewer, space_id), "Average price")))

    assert message["attempts"] == 2 and message["status"] == "ok"


# ── Writing rules ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expression",
    [
        "region = (SELECT max(region) FROM sales)",
        "other.region = 'East'",
        "nonsense = 1",
        "sum(amount) > 5",
        "region = 'East'; DROP TABLE sales",
        "amount > 'abc'",
        "SELECT 1",
        "",
    ],
)
def test_a_row_filter_that_could_reach_other_data_or_does_not_run_is_refused(
    api: TestClient, expression: str
) -> None:
    boss, _, _, space_id, tid = setup(api)

    response = rule(
        boss, space_id, table_id=tid, kind="row_filter", expression=expression, audience="viewers"
    )

    assert response.status_code == 400 and code(response) == "invalid_rule"
    assert boss.get(f"/spaces/{space_id}/access-rules").json() == []


def test_only_real_columns_can_be_hidden(api: TestClient) -> None:
    boss, _, _, space_id, tid = setup(api)

    response = rule(
        boss, space_id, table_id=tid, kind="hide_column", column="nope", audience="viewers"
    )

    assert response.status_code == 400 and code(response) == "invalid_rule"


def test_only_administrators_can_see_or_change_the_rules(api: TestClient) -> None:
    boss, viewer, editor, space_id, tid = setup(api)
    made = rule(
        boss, space_id, table_id=tid, kind="hide_column", column="unit_price", audience="members"
    ).json()

    for who in (viewer, editor):
        assert who.get(f"/spaces/{space_id}/access-rules").status_code == 403
        assert (
            rule(
                who, space_id, table_id=tid, kind="hide_column", column="amount", audience="viewers"
            ).status_code
            == 403
        )
        assert who.delete(f"/spaces/{space_id}/access-rules/{made['id']}").status_code == 403


def test_a_rule_can_be_listed_and_removed_and_then_no_longer_applies(api: TestClient) -> None:
    boss, viewer, _, space_id, tid = setup(api)
    made = rule(
        boss, space_id, table_id=tid, kind="hide_column", column="unit_price", audience="viewers"
    ).json()

    listed = boss.get(f"/spaces/{space_id}/access-rules").json()
    assert [(r["table"], r["kind"], r["column"], r["audience"]) for r in listed] == [
        ("sales", "hide_column", "unit_price", "viewers")
    ]
    assert boss.delete(f"/spaces/{space_id}/access-rules/{made['id']}").status_code == 204

    assert "unit_price" in [c["name"] for c in preview(viewer, space_id, tid)["columns"]]
