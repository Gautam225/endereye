"""Deep analysis (a request split into analyses, each solved on its own) and quick mode."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.chat.deep import DeepPlan, PlanStep
from app.llm.errors import LLMNotConfiguredError

pytestmark = pytest.mark.db

BY_REGION = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
BY_STATUS = "SELECT status, count(*) AS orders FROM sales GROUP BY 1 ORDER BY 1"
BROKEN = "SELECT nope FROM sales"
PLAN = DeepPlan(
    steps=[
        PlanStep(title="Revenue by region", question="What is the revenue of each region?"),
        PlanStep(title="Orders by status", question="How many orders are there per status?"),
    ],
    assumptions=["Revenue means the sum of the amount column."],
    limitations=["There is no profit column, so margins cannot be worked out."],
)


def run(
    api: TestClient, fake: FakeLLM, mode: str = "deep", who: str = "boss", space: object = None
) -> tuple[list, dict]:
    boss = admin(api)
    space_id = small_space(boss)
    use(api, fake)
    cid = conversation(boss, space_id)
    found = events(ask(boss, space_id, cid, "Prepare an analysis of sales", mode=mode))
    return found, final(found)


def test_a_big_request_is_split_into_analyses_that_are_each_solved(api: TestClient) -> None:
    fake = FakeLLM(chat_plan=[PLAN], chat_sql=[sql_plan(BY_REGION), sql_plan(BY_STATUS)])

    found, message = run(api, fake)

    assert message["mode"] == "deep" and message["status"] == "ok"
    steps = message["steps"]
    assert [(s["title"], s["status"], s["sql"]) for s in steps] == [
        ("Revenue by region", "ok", BY_REGION),
        ("Orders by status", "ok", BY_STATUS),
    ]
    assert steps[0]["row_count"] == 4 and steps[0]["chart"]["type"] == "bar"
    assert steps[0]["summary"].startswith("4 rows. Highest revenue")
    assert [d["index"] for n, d in found if n == "step"] == [1, 2]  # each arrives as it finishes
    assert "chat_explain" not in fake.purposes()  # no result row went to the AI service
    assert message["sql"] == BY_REGION  # the first analysis is what the exports use


def test_the_answer_lists_what_was_done_the_assumptions_and_what_the_data_cannot_say(
    api: TestClient,
) -> None:
    fake = FakeLLM(chat_plan=[PLAN], chat_sql=[sql_plan(BY_REGION), sql_plan(BY_STATUS)])

    _, message = run(api, fake)

    answer = message["answer"]
    assert "split it into 2 analyses" in answer
    assert (
        "1. **Revenue by region**: Done." in answer and "2. **Orders by status**: Done." in answer
    )
    assert "**Assumptions**" in answer and "sum of the amount column" in answer
    assert "**Not possible with this data**" in answer and "no profit column" in answer
    assert message["assumptions"] == ["Revenue means the sum of the amount column."]


def test_a_stubborn_analysis_fails_alone_and_the_others_still_come_back(api: TestClient) -> None:
    fake = FakeLLM(
        chat_plan=[PLAN],
        chat_sql=[sql_plan(BY_REGION), sql_plan(BROKEN)],
        chat_repair=[sql_plan(BROKEN)],
    )

    _, message = run(api, fake)

    assert message["status"] == "ok"
    first, second = message["steps"]
    assert first["status"] == "ok" and second["status"] == "failed"
    assert second["rows"] is None and "could not be completed" in second["summary"]
    assert "2. **Orders by status**: Failed." in message["answer"]
    assert fake.purposes().count("chat_repair") == 2  # tried again, never in a loop


def test_when_nothing_can_be_solved_the_turn_fails_plainly(api: TestClient) -> None:
    fake = FakeLLM(chat_plan=[PLAN], chat_sql=[sql_plan(BROKEN)], chat_repair=[sql_plan(BROKEN)])

    found, message = run(api, fake)

    assert message["status"] == "failed" and message["error_code"] == "sql_failed"
    assert "error" in [n for n, _ in found]


def test_a_plan_of_one_analysis_is_answered_the_usual_way(api: TestClient) -> None:
    one = DeepPlan(steps=[PlanStep(title="Revenue", question="Revenue by region?")])
    fake = FakeLLM(chat_plan=[one], chat_sql=[sql_plan(BY_REGION)])

    found, message = run(api, fake)

    assert message["steps"] == [] and message["sql"] == BY_REGION
    notes = [d["text"] for n, d in found if n == "thought" and d["kind"] == "note"]
    assert any("fits in one query" in note for note in notes)


def test_when_no_plan_can_be_made_it_still_answers(api: TestClient) -> None:
    fake = FakeLLM(chat_plan=[LLMNotConfiguredError()], chat_sql=[sql_plan(BY_REGION)])

    _, message = run(api, fake)

    assert message["steps"] == [] and message["status"] == "ok"


def test_the_planner_is_told_the_tables_the_rules_and_to_assume_not_ask(api: TestClient) -> None:
    fake = FakeLLM(chat_plan=[PLAN], chat_sql=[sql_plan(BY_REGION), sql_plan(BY_STATUS)])

    run(api, fake)

    (prompt,) = fake.prompts("chat_plan")
    assert "Table sales" in prompt and "region" in prompt
    assert "Do not ask questions" in prompt and "limitations" in prompt
    first_sql = fake.prompts("chat_sql")[0]
    assert "What is the revenue of each region?" in first_sql  # each analysis stands alone


def test_deep_analyses_run_inside_the_same_access_limits(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    viewer = person(api, boss, "vera@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    table = boss.get(f"/spaces/{space_id}/tables").json()[0]["id"]
    boss.post(
        f"/spaces/{space_id}/access-rules",
        json={
            "table_id": table,
            "kind": "row_filter",
            "expression": "region = 'East'",
            "audience": "viewers",
        },
    )
    use(api, FakeLLM(chat_plan=[PLAN], chat_sql=[sql_plan(BY_REGION), sql_plan(BY_STATUS)]))

    found = events(
        ask(viewer, space_id, conversation(viewer, space_id), "Analyse sales", mode="deep")
    )

    step = final(found)["steps"][0]
    assert [row[0] for row in step["rows"]] == ["East"]


# ── Quick mode ───────────────────────────────────────────────────────────────


def test_quick_mode_uses_the_fast_model_and_writes_the_answer_here(api: TestClient) -> None:
    fake = FakeLLM(chat_sql=[sql_plan(BY_REGION)])

    _, message = run(api, fake, mode="quick")

    assert message["mode"] == "quick" and message["status"] == "ok"
    assert [(p, tier) for p, tier, _ in fake.calls] == [("chat_sql", "fast")]
    assert message["answer"].startswith("4 rows. Highest revenue")  # built from the rows
    assert message["steps"] == []


def test_standard_mode_is_what_you_get_without_choosing(api: TestClient) -> None:
    fake = FakeLLM(chat_sql=[sql_plan(BY_REGION)])
    boss = admin(api)
    space_id = small_space(boss)
    use(api, fake)

    found = events(ask(boss, space_id, conversation(boss, space_id), "Revenue by region"))

    assert final(found)["mode"] == "standard"
    assert [(p, tier) for p, tier, _ in fake.calls][:1] == [("chat_sql", "smart")]
    assert "chat_explain" in fake.purposes()
