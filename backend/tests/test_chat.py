"""Chat end to end: question, SQL, run, repair, follow-ups, access, stop, CSV.

The AI is a scripted stand-in (no network, no quota); retrieval uses the real local models.
"""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import json
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_knowledge import POLICY, sales_csv
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.chat.answer import Explanation
from app.chat.context import select_tables, value_candidates
from app.chat.prompts import SqlPlan
from app.llm.errors import LLMNotConfiguredError
from app.llm.gateway import get_llm
from app.rag import cards, retrieval
from app.services.conversations import csv_cell, runs, to_csv

pytestmark = pytest.mark.db

REVENUE_SQL = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"


class FakeLLM:
    """Answers each kind of call from a script. The last item of a script repeats."""

    configured = True

    def __init__(self, **scripts: list[Any]) -> None:
        scripts.setdefault("chat_explain", [explanation()])
        self.scripts = {purpose: list(items) for purpose, items in scripts.items()}
        self.calls: list[tuple[str, str, list[dict[str, Any]]]] = []

    async def complete_json(
        self, messages: list[dict[str, Any]], schema: Any, *, purpose: str, tier: str = "smart"
    ) -> tuple[Any, Any]:
        self.calls.append((purpose, tier, messages))
        script = self.scripts.get(purpose)
        assert script, f"unexpected AI call: {purpose}"
        item = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(item, Exception):
            raise item
        return item, SimpleNamespace(provider="fake", model="model-1")

    def prompts(self, purpose: str) -> list[str]:
        return [
            "\n".join(str(m["content"]) for m in messages)
            for p, _, messages in self.calls
            if p == purpose
        ]

    def purposes(self) -> list[str]:
        return [p for p, _, _ in self.calls]


def explanation(summary: str = "Here are the results.", **kwargs: Any) -> Explanation:
    kwargs.setdefault("follow_ups", ["Show this by month?", "Which region is highest?"])
    kwargs.setdefault("title", "Revenue by region")
    return Explanation(summary=summary, **kwargs)


def sql_plan(sql: str, **kwargs: Any) -> SqlPlan:
    return SqlPlan(action="sql", plan="Group sales by region.", sql=sql, **kwargs)


def rewrite(text: str) -> Any:
    return SimpleNamespace(standalone_question=text)


def use(api: TestClient, fake: FakeLLM) -> None:
    api.app.dependency_overrides[get_llm] = lambda: fake


def events(response: Any) -> list[tuple[str, Any]]:
    assert response.status_code == 200, response.text
    found, name = [], None
    for line in response.text.splitlines():
        if line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:") and name:
            found.append((name, json.loads(line.removeprefix("data:").strip())))
            name = None
    return found


def names(found: list[tuple[str, Any]]) -> list[str]:
    return [n for n, _ in found]


def final(found: list[tuple[str, Any]]) -> dict[str, Any]:
    done = [data for name, data in found if name == "done"]
    assert len(done) == 1, names(found)
    return done[0]


def small_space(boss: Any) -> str:
    space_id = new_space(boss)
    assert boss.upload(space_id, "sales.csv", sales_csv()).status_code == 201
    return space_id


def conversation(person_: Any, space_id: str, title: str | None = None) -> str:
    response = person_.post(f"/spaces/{space_id}/conversations", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask(person_: Any, space_id: str, cid: str, question: str, **extra: Any) -> Any:
    return person_.post(
        f"/spaces/{space_id}/conversations/{cid}/messages", json={"question": question, **extra}
    )


# ── A question, start to finish ──────────────────────────────────────────────


def test_a_question_becomes_sql_rows_and_a_saved_answer(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    fake = FakeLLM(chat_sql=[sql_plan(REVENUE_SQL, assumptions=["Used all dates."])])
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Total revenue by region?"))

    core = [n for n in names(found) if n not in {"thought", "answer.delta"}]
    assert core == [
        "start",
        "status",
        "status",
        "sql",
        "status",
        "rows",
        "status",
        "answer",
        "chart",
        "suggestions",
        "title",
        "done",
    ]
    assert "thought" in names(found) and "answer.delta" in names(found)
    stages = [d["stage"] for n, d in found if n == "status"]
    assert stages == ["retrieving", "writing_sql", "running", "explaining"]
    message = final(found)
    assert (message["status"], message["sql"], message["attempts"]) == ("ok", REVENUE_SQL, 1)
    assert [c["name"] for c in message["columns"]] == ["region", "revenue"]
    assert message["row_count"] == 4 and message["assumptions"] == ["Used all dates."]
    assert message["answer"] == "Here are the results."
    assert message["chart"] == {
        "type": "bar",
        "x": "region",
        "y": ["revenue"],
        "series": None,
        "title": "Revenue by region",
        "partial": False,
    }
    assert message["suggestions"] == ["Show this by month?", "Which region is highest?"]
    assert set(message["timings"]) >= {"retrieve", "write_sql", "execute", "explain", "total"}
    assert message["models"] == ["fake/model-1"]
    assert fake.purposes() == ["chat_sql", "chat_explain"]  # a first question needs no rewrite

    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()
    assert saved["title"] == "Revenue by region"  # the AI's title replaced the first question
    assert [m["id"] for m in saved["messages"]] == [message["id"]]
    assert saved["messages"][0]["rows"] == message["rows"] and message["rows"][0][0] == "East"


def test_the_prompt_carries_the_spaces_context_and_nothing_hidden(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={"kind": "instruction", "body": "Always exclude cancelled orders."},
    )
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={
            "kind": "example_sql",
            "title": "What is the total revenue by region?",
            "body": "SELECT region, sum(amount) FROM sales WHERE status <> 'cancelled' GROUP BY 1",
        },
    )
    table = boss.get(f"/spaces/{space_id}/metadata").json()[0]
    unit = next(c for c in table["columns"] if c["name"] == "unit_price")
    boss.patch(
        f"/spaces/{space_id}/tables/{table['id']}/columns/{unit['id']}", json={"hidden": True}
    )
    viewer = person(api, boss, "vera@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    cid = conversation(viewer, space_id)
    fake = FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)])
    use(api, fake)

    found = events(ask(viewer, space_id, cid, "What is the total revenue by region?"))

    assert final(found)["status"] == "ok"  # viewers can ask
    (prompt,) = fake.prompts("chat_sql")
    assert "Table sales" in prompt and "region" in prompt
    assert "Always exclude cancelled orders." in prompt
    assert "Question: What is the total revenue by region?" in prompt
    assert "unit_price" not in prompt and "Earlier in this conversation" not in prompt
    assert "single DuckDB" not in prompt  # the schema text, not leaked instructions about itself


# ── Follow-ups and isolation ─────────────────────────────────────────────────


def test_a_follow_up_is_rewritten_with_this_threads_history_only(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    first, second = conversation(boss, space_id), conversation(boss, space_id)
    fake = FakeLLM(
        chat_sql=[sql_plan(REVENUE_SQL)],
        chat_rewrite=[rewrite("Total revenue by region, only for completed orders")],
    )
    use(api, fake)

    events(ask(boss, space_id, first, "Revenue by region please"))
    follow = final(events(ask(boss, space_id, first, "and only completed ones?")))
    other = final(events(ask(boss, space_id, second, "How many orders are there?")))

    assert follow["standalone_question"] == "Total revenue by region, only for completed orders"
    (rewrite_prompt,) = fake.prompts("chat_rewrite")
    assert (
        "Revenue by region please" in rewrite_prompt
        and "and only completed ones?" in rewrite_prompt
    )
    follow_prompt = fake.prompts("chat_sql")[1]
    assert "Revenue by region please" in follow_prompt
    assert "Earlier in this conversation" in follow_prompt and REVENUE_SQL in follow_prompt
    assert "only for completed orders" in follow_prompt
    # The other thread sees nothing from the first one, and needs no rewrite.
    other_prompt = fake.prompts("chat_sql")[2]
    assert "Revenue by region please" not in other_prompt and REVENUE_SQL not in other_prompt
    assert "Earlier in this conversation" not in other_prompt
    assert fake.purposes() == [
        "chat_sql",
        "chat_explain",
        "chat_rewrite",
        "chat_sql",
        "chat_explain",
        "chat_sql",
        "chat_explain",
    ]
    assert other["status"] == "ok"


def test_editing_a_question_replaces_it_and_what_came_after(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    fake = FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)], chat_rewrite=[rewrite("x")])
    use(api, fake)
    first = final(events(ask(boss, space_id, cid, "Revenue by region")))
    second = final(events(ask(boss, space_id, cid, "Only for the north")))
    events(ask(boss, space_id, cid, "And the south"))

    edited = final(
        events(ask(boss, space_id, cid, "Only for the east", replace_message_id=second["id"]))
    )

    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"]
    assert [(m["seq"], m["question"]) for m in saved] == [
        (1, "Revenue by region"),
        (2, "Only for the east"),
    ]
    assert edited["id"] != second["id"] and saved[0]["id"] == first["id"]
    gone = ask(boss, space_id, cid, "x", replace_message_id=second["id"])
    assert gone.status_code == 404


# ── Repair, giving up, and the other answers ─────────────────────────────────


def test_a_query_that_fails_is_repaired_with_the_error(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    fake = FakeLLM(
        chat_sql=[sql_plan("SELECT region, sum(revenue) FROM sales GROUP BY 1")],
        chat_repair=[sql_plan(REVENUE_SQL)],
    )
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Revenue by region"))

    message = final(found)
    assert (message["status"], message["attempts"], message["sql"]) == ("ok", 2, REVENUE_SQL)
    assert [d["stage"] for n, d in found if n == "status"].count("repairing") == 1
    (repair_prompt,) = fake.prompts("chat_repair")
    assert "did not work" in repair_prompt and "revenue" in repair_prompt


@pytest.mark.parametrize(
    "bad_sql",
    ["DROP TABLE sales", "SELECT * FROM secrets", "SELECT * FROM read_csv('/etc/passwd')"],
    ids=["drop", "unknown-table", "file-read"],
)
def test_the_guard_stops_unsafe_sql_and_the_model_gets_to_fix_it(
    api: TestClient, bad_sql: str
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    fake = FakeLLM(chat_sql=[sql_plan(bad_sql)], chat_repair=[sql_plan(REVENUE_SQL)])
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Revenue by region"))

    sqls = [d["sql"] for n, d in found if n == "sql"]
    assert sqls == [REVENUE_SQL]  # the unsafe query was never shown as run, nor executed
    assert final(found)["attempts"] == 2


def test_it_gives_up_after_three_tries_and_says_so(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    broken = sql_plan("SELECT nothing FROM sales")
    fake = FakeLLM(chat_sql=[broken], chat_repair=[broken])
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Something impossible"))

    message = final(found)
    assert (message["status"], message["error_code"], message["attempts"]) == (
        "failed",
        "sql_failed",
        3,
    )
    assert message["sql"] == "SELECT nothing FROM sales"  # kept, so an editor can look at it
    assert len(fake.prompts("chat_repair")) == 2
    error = next(d for n, d in found if n == "error")
    assert error["code"] == "sql_failed" and "nothing" in error["detail"]


def test_a_query_with_no_rows_is_an_empty_result_not_an_error(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    nowhere = sql_plan("SELECT * FROM sales WHERE region = 'Nowhere'")
    # a filtered query that finds nothing is checked once more; a second empty result stands
    use(api, FakeLLM(chat_sql=[nowhere], chat_repair=[nowhere]))

    message = final(events(ask(boss, space_id, cid, "Sales in Nowhere")))

    assert (message["status"], message["row_count"], message["rows"]) == ("empty", 0, [])
    assert "no rows" in message["answer"]


def test_clarifying_and_declining_are_answers_too(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    clarify = SqlPlan(action="clarify", clarification="Which year do you mean?")
    decline = SqlPlan(action="decline", answer="There is no salary data in this space.")
    fake = FakeLLM(chat_sql=[clarify, decline, SqlPlan(action="answer", answer="From nowhere")])
    use(api, fake)

    asked = final(events(ask(boss, space_id, conversation(boss, space_id), "Show sales")))
    declined = final(
        events(ask(boss, space_id, conversation(boss, space_id), "What are salaries?"))
    )
    no_documents = final(
        events(ask(boss, space_id, conversation(boss, space_id), "What does the policy say?"))
    )

    assert (asked["status"], asked["answer"], asked["sql"]) == (
        "clarify",
        "Which year do you mean?",
        None,
    )
    assert (declined["status"], declined["answer"]) == (
        "declined",
        "There is no salary data in this space.",
    )
    assert no_documents["status"] == "declined"  # "answer from documents" with none to use


def test_a_question_comes_with_answers_to_pick_from_and_they_are_saved(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    clarify = SqlPlan(
        action="clarify",
        clarification="Which revenue do you mean?",
        options=["Total revenue", " total revenue ", "Revenue of completed orders", "", "x" * 300],
    )
    fake = FakeLLM(chat_sql=[clarify, SqlPlan(action="clarify", clarification="Which one?")])
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Show our revenue"))
    plain = final(events(ask(boss, space_id, cid, "And the other?")))

    asked = final(found)
    # trimmed, no repeats (even in another case), nothing empty or too long
    assert asked["options"] == ["Total revenue", "Revenue of completed orders"]
    assert [d for n, d in found if n == "options"] == [{"options": asked["options"]}]
    order = [n for n, _ in found]
    assert order.index("answer") < order.index("options") < order.index("done")
    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"]
    assert saved[0]["options"] == asked["options"]  # still there after a reload
    assert plain["options"] == []  # a question without choices has none


def test_two_analyses_in_one_query_are_drawn_as_two_charts_not_one_mixed_chart(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    stacked = (
        "SELECT 'Region' AS breakdown, region AS label, count(*) AS orders FROM sales "
        "GROUP BY region UNION ALL "
        "SELECT 'Status', status, count(*) FROM sales GROUP BY status"
    )
    use(api, FakeLLM(chat_sql=[sql_plan(stacked)]))

    cid = conversation(boss, space_id)
    found = events(ask(boss, space_id, cid, "Analyse by region and status"))

    message = final(found)
    chart = message["chart"]
    assert (chart["facet"], chart["x"], chart["y"]) == ("breakdown", "label", ["orders"])
    assert [(p["value"], p["type"]) for p in chart["panels"]] == [
        ("Region", "bar"),
        ("Status", "bar"),
    ]
    assert [d for n, d in found if n == "chart"] == [chart]  # one chart event, with both panels
    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()
    assert saved["messages"][0]["chart"]["panels"] == chart["panels"]  # still two after a reload


def test_a_combined_chart_is_asked_for_again_when_the_result_stacks_separate_analyses(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    stacked = (
        "SELECT 'Region' AS breakdown, region AS label, count(*) AS orders FROM sales "
        "GROUP BY region UNION ALL "
        "SELECT 'Status', status, count(*) FROM sales GROUP BY status"
    )
    combined = (
        "SELECT region, status, count(*) AS orders FROM sales GROUP BY region, status "
        "ORDER BY region, status"
    )
    fake = FakeLLM(chat_sql=[sql_plan(stacked)], chat_repair=[sql_plan(combined)])
    use(api, fake)
    cid = conversation(boss, space_id)

    found = events(ask(boss, space_id, cid, "Analyse by region and status in a combined graph"))
    other = conversation(boss, space_id)  # a new chat: nothing earlier to read it as a follow-up
    separate = final(events(ask(boss, space_id, other, "Analyse by region and by status")))

    message = final(found)
    assert message["attempts"] == 2 and message["sql"] == combined
    assert message["chart"]["series"] is not None and "panels" not in message["chart"]
    notes = [d["text"] for n, d in found if n == "thought" and d["kind"] == "note"]
    assert any("combined in one chart" in note for note in notes)
    (repair,) = fake.prompts("chat_repair")
    assert "stacks separate breakdowns" in repair
    # without the word "combined" the stacked result is right, and is not redone
    assert separate["attempts"] == 1 and "panels" in separate["chart"]


def test_picking_an_answer_continues_the_conversation_with_the_question_in_mind(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    clarify = SqlPlan(
        action="clarify",
        clarification="Which revenue do you mean?",
        options=["Total revenue", "Revenue of completed orders"],
    )
    fake = FakeLLM(
        chat_sql=[clarify, sql_plan(REVENUE_SQL)],
        chat_rewrite=[rewrite("Show the total revenue by region.")],
    )
    use(api, fake)

    asked = final(events(ask(boss, space_id, cid, "Show our revenue")))
    # what the answer card sends for a picked option plus words typed by the person
    answered = final(events(ask(boss, space_id, cid, "Total revenue. By region")))

    assert asked["status"] == "clarify" and asked["options"] == clarify.options
    (rewriting,) = fake.prompts("chat_rewrite")
    assert "Which revenue do you mean?" in rewriting and "Total revenue. By region" in rewriting
    assert answered["status"] == "ok" and answered["row_count"] == 4  # a real result now


def test_the_answers_offered_with_a_question_are_cleaned() -> None:
    from app.chat.pipeline import clean_options

    assert clean_options(["A", "B"]) == ["A", "B"]
    assert clean_options(["  A  b ", "a B", "C"]) == ["A b", "C"]
    assert clean_options(["Only one"]) == []  # one answer is not a choice
    assert clean_options(["Which year?", "2025"], "Which year?") == []  # not the question itself
    assert clean_options([str(i) for i in range(10)]) == ["0", "1", "2", "3", "4"]
    assert clean_options(["", "  ", "x" * 121, "ok", "fine"]) == ["ok", "fine"]


def test_a_question_can_be_answered_from_a_document(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    boss.post(f"/spaces/{space_id}/documents", files={"file": ("policy.md", POLICY.encode())})
    cid = conversation(boss, space_id)
    fake = FakeLLM(
        chat_sql=[SqlPlan(action="answer", answer="Returns are accepted within thirty days.")]
    )
    use(api, fake)

    message = final(events(ask(boss, space_id, cid, "What is the return window?")))

    assert (message["status"], message["sql"]) == ("answer", None)
    assert "thirty days" in message["answer"]
    documents = [s for s in message["sources"] if s["type"] == "document"]
    assert [s["header"] for s in documents] == ["policy"]  # the document once, not each section
    assert "thirty days of delivery" in fake.prompts("chat_sql")[0]


def test_sql_that_matches_a_trusted_example_is_marked_trusted(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={
            "kind": "example_sql",
            "title": "What is the total revenue by region?",
            "body": REVENUE_SQL,
            "trusted": True,
        },
    )
    cid = conversation(boss, space_id)
    use(
        api,
        FakeLLM(
            chat_sql=[
                sql_plan(REVENUE_SQL.lower() + " ;"),
                sql_plan("SELECT region, count(*) AS orders FROM sales GROUP BY 1"),
            ]
        ),
    )

    same = final(events(ask(boss, space_id, cid, "What is the total revenue by region?")))
    different = final(events(ask(boss, space_id, cid, "Orders per region?")))

    assert same["trusted"] is True and different["trusted"] is False


def test_ai_problems_become_a_failed_answer_with_a_reason(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[LLMNotConfiguredError()]))

    found = events(ask(boss, space_id, cid, "Revenue by region"))

    message = final(found)
    assert (message["status"], message["error_code"]) == ("failed", "llm_not_configured")
    assert dict(found)["error"]["code"] == "llm_not_configured"
    assert "Traceback" not in json.dumps(found)


# ── Access ───────────────────────────────────────────────────────────────────


def test_threads_are_private_and_need_membership(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    other_space = new_space(boss, "Other")
    member = person(api, boss, "mia@example.com", "viewer")
    outsider = person(api, boss, "olga@example.com", "editor")
    peer = person(api, boss, "pat@example.com", "viewer")
    for who in (member, peer):
        boss.put(f"/spaces/{space_id}/members/{who.id}", json={"role": "viewer"})
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)]))
    cid = conversation(member, space_id)
    message = final(events(ask(member, space_id, cid, "Revenue by region")))
    base = f"/spaces/{space_id}/conversations/{cid}"

    assert outsider.post(f"/spaces/{space_id}/conversations", json={}).status_code == 404
    assert outsider.get(f"/spaces/{space_id}/conversations").status_code == 404
    for stranger in (peer, boss):  # even a fellow member, even the admin
        assert stranger.get(base).status_code == 404
        assert stranger.patch(base, json={"title": "x"}).status_code == 404
        assert stranger.delete(base).status_code == 404
        assert ask(stranger, space_id, cid, "hi").status_code == 404
        assert stranger.post(f"{base}/messages/{message['id']}/cancel").status_code == 404
        assert stranger.get(f"{base}/messages/{message['id']}/csv").status_code == 404
        assert stranger.get(f"/spaces/{space_id}/conversations").json() == []
    assert boss.get(f"/spaces/{other_space}/conversations/{cid}").status_code == 404
    assert [c["id"] for c in member.get(f"/spaces/{space_id}/conversations").json()] == [cid]


def test_threads_can_be_listed_searched_renamed_and_deleted(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)]))
    first = conversation(boss, space_id)
    events(ask(boss, space_id, first, "Revenue by region"))
    second = conversation(boss, space_id, "Quarterly review")
    base = f"/spaces/{space_id}/conversations"

    assert [c["id"] for c in boss.get(base).json()] == [second, first]  # newest first
    assert [c["id"] for c in boss.get(base, params={"q": "REGION"}).json()] == [first]
    assert [c["id"] for c in boss.get(base, params={"q": "quarterly"}).json()] == [second]
    assert boss.get(base, params={"q": "100%"}).json() == []  # "%" is not a wildcard
    assert boss.patch(f"{base}/{first}", json={"title": "Regions"}).json()["title"] == "Regions"
    assert boss.patch(f"{base}/{first}", json={"title": "  "}).status_code == 422
    assert boss.delete(f"{base}/{first}").status_code == 204
    assert [c["id"] for c in boss.get(base).json()] == [second]


def test_only_one_answer_runs_at_a_time_in_a_thread(api: TestClient, sql: Any) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    sql(
        "INSERT INTO messages (id, conversation_id, seq, question, status) "
        "VALUES (gen_random_uuid(), :c, 1, 'earlier', 'running')",
        {"c": cid},
    )
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)]))

    response = ask(boss, space_id, cid, "Another question")

    assert (response.status_code, code(response)) == (409, "turn_running")


def test_questions_are_validated(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)]))

    assert ask(boss, space_id, cid, "   ").status_code == 422
    assert ask(boss, space_id, cid, "x" * 2001).status_code == 422


# ── Stop and download ────────────────────────────────────────────────────────


def test_stopping_a_running_query_ends_the_turn_quickly(api: TestClient, sql: Any) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    slow = "SELECT count(*) FROM range(3000000000) a(x) WHERE x % 7 = 3"
    use(api, FakeLLM(chat_sql=[sql_plan(slow)]))

    def stop_when_running() -> None:
        for _ in range(200):
            rows = sql(
                "SELECT id FROM messages WHERE conversation_id = :c AND sql IS NOT NULL "
                "AND status = 'running'",
                {"c": cid},
            )
            if rows:
                time.sleep(0.5)  # let the query actually start
                assert runs.stop(rows[0][0])
                return
            time.sleep(0.1)

    stopper = threading.Thread(target=stop_when_running)
    stopper.start()
    started = time.perf_counter()
    found = events(ask(boss, space_id, cid, "Count something huge"))
    stopper.join()

    assert time.perf_counter() - started < 30
    assert final(found)["status"] == "cancelled"
    assert dict(found)["error"]["code"] == "cancelled"
    assert boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]["status"] == (
        "cancelled"
    )


def test_a_page_that_reconnects_gets_the_whole_answer_again(api: TestClient) -> None:
    """The turn runs on the server by itself; `events` rejoins it after a refresh."""
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)]))
    first = events(ask(boss, space_id, cid, "Revenue by region?"))
    message_id = dict(first)["start"]["message_id"]

    again = events(boss.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message_id}/events"))

    assert names(again) == names(first)
    assert final(again)["id"] == final(first)["id"]


def test_rejoining_an_answer_nobody_is_writing_ends_it_honestly(api: TestClient, sql: Any) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    sql(
        "INSERT INTO messages (id, conversation_id, seq, question, status) "
        "VALUES (gen_random_uuid(), :c, 1, 'earlier', 'running')",
        {"c": cid},
    )
    message_id = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]["id"]

    found = events(boss.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message_id}/events"))

    assert names(found) == ["done"]
    assert (final(found)["status"], final(found)["error_code"]) == ("failed", "lost")


def test_the_result_downloads_as_csv_with_formulas_neutralised(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    boss.upload(space_id, "notes.csv", b"who,what\nann,=SUM(1+1)\nbob,plain\ncy,@cmd\ndi,\n")
    cid = conversation(boss, space_id, "Notes & remarks!")
    use(api, FakeLLM(chat_sql=[sql_plan("SELECT who, what FROM notes ORDER BY who")]))
    message = final(events(ask(boss, space_id, cid, "Show the notes")))

    response = boss.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message['id']}/csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="notes-remarks.csv"' in response.headers["content-disposition"]
    assert response.text.splitlines() == [
        "who,what",
        "ann,'=SUM(1+1)",
        "bob,plain",
        "cy,'@cmd",
        "di,",
    ]


def test_a_message_without_a_query_has_nothing_to_download(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[SqlPlan(action="decline", answer="No.")]))
    message = final(events(ask(boss, space_id, cid, "Anything?")))

    response = boss.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message['id']}/csv")

    assert response.status_code == 404


# ── Small pure parts ─────────────────────────────────────────────────────────


def test_csv_cells_and_files() -> None:
    assert csv_cell("=1+1") == "'=1+1" and csv_cell("-5") == "'-5" and csv_cell(None) == ""
    assert csv_cell(12) == 12 and csv_cell("hello") == "hello"
    assert to_csv(["a", "b"], [["x,y", 'say "hi"'], [None, 3]]) == (
        'a,b\r\n"x,y","say ""hi"""\r\n,3\r\n'
    )


def test_value_candidates_skip_filler_and_keep_pairs() -> None:
    found = value_candidates("How many customers are in Tamil Nadu last year?")

    assert "Tamil Nadu" in found and "Tamil" in found and "Nadu" in found
    assert "How" not in found and "many" not in found and "last" not in found


def test_tables_are_chosen_from_what_was_retrieved_plus_their_joins() -> None:
    def table(name: str) -> cards.TableInfo:
        return cards.TableInfo(name, name, "", 1, ())

    tables = [table("customers"), table("orders"), table("stores"), table("tags")]
    joins = [cards.JoinInfo("orders", "customer_id", "customers", "id", "many_to_one")]
    passage = retrieval.Passage("h", "t", "column", 1.0, (1,), {"table": "orders"})

    chosen = select_tables([passage], tables, joins)

    assert [t.name for t in chosen] == ["orders", "customers"]  # tags and stores are not related
    assert [t.name for t in select_tables([], tables, joins)] == [t.name for t in tables]


# ── The written answer, charts and follow-ups ────────────────────────────────


def test_the_summary_is_kept_when_its_numbers_come_from_the_result(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    fake = FakeLLM(
        chat_sql=[sql_plan(REVENUE_SQL)],
        chat_explain=[explanation("Across 4 regions, revenue is spread fairly evenly.")],
    )
    use(api, fake)

    message = final(events(ask(boss, space_id, cid, "Revenue by region")))

    assert message["answer"] == "Across 4 regions, revenue is spread fairly evenly."
    (prompt,) = fake.prompts("chat_explain")
    assert "Question: Revenue by region" in prompt and "region | revenue" in prompt
    assert "Summary figures over all rows" in prompt and "sales: " in prompt
    assert fake.calls[-1][1] == "fast"  # the cheap model writes the answer


def test_a_summary_with_an_invented_number_is_replaced_by_one_built_from_the_data(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(
        api,
        FakeLLM(
            chat_sql=[sql_plan(REVENUE_SQL)],
            chat_explain=[explanation("Revenue grew 37% and reached 9,999,999.")],
        ),
    )

    message = final(events(ask(boss, space_id, cid, "Revenue by region")))

    assert "37%" not in message["answer"] and "9,999,999" not in message["answer"]
    assert message["answer"].startswith("4 rows. Highest revenue: ")
    assert message["status"] == "ok" and message["chart"]["type"] == "bar"


def test_the_result_is_still_shown_when_the_answer_cannot_be_written(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(
        api,
        FakeLLM(chat_sql=[sql_plan(REVENUE_SQL)], chat_explain=[LLMNotConfiguredError()]),
    )

    found = events(ask(boss, space_id, cid, "Revenue by region"))

    message = final(found)
    assert message["status"] == "ok" and message["row_count"] == 4
    assert message["answer"].startswith("4 rows. Highest revenue: ")
    assert message["suggestions"] == [] and message["chart"] is not None
    assert "error" not in names(found) and "suggestions" not in names(found)


def test_follow_ups_are_cleaned_and_titles_respect_renames(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    named = conversation(boss, space_id, "Quarterly review")
    auto = conversation(boss, space_id)
    follow_ups = ["Revenue by region", "Show by month?", "show by month?", "Which is best?"]
    use(
        api,
        FakeLLM(
            chat_sql=[sql_plan(REVENUE_SQL)],
            chat_explain=[explanation(follow_ups=follow_ups, title='  "Region revenue"  ')],
        ),
    )

    kept = final(events(ask(boss, space_id, named, "Revenue by region")))
    retitled = events(ask(boss, space_id, auto, "Revenue by region"))

    assert kept["suggestions"] == ["Show by month?", "Which is best?"]  # not the question itself
    base = f"/spaces/{space_id}/conversations"
    assert boss.get(f"{base}/{named}").json()["title"] == "Quarterly review"
    assert boss.get(f"{base}/{auto}").json()["title"] == "Region revenue"
    assert dict(retitled)["title"] == {"title": "Region revenue"}


def test_an_empty_result_needs_no_ai_answer_and_has_no_chart(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    nowhere = sql_plan("SELECT * FROM sales WHERE region = 'Nowhere'")
    fake = FakeLLM(chat_sql=[nowhere], chat_repair=[nowhere])
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Sales in Nowhere"))

    message = final(found)
    assert (message["chart"], message["suggestions"]) == (None, [])
    assert "chat_explain" not in fake.purposes() and "explaining" not in str(found)


def test_a_big_result_keeps_a_preview_marks_its_chart_partial_and_downloads_in_full(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[sql_plan("SELECT x, x * 2 AS doubled FROM range(500) t(x)")]))

    message = final(events(ask(boss, space_id, cid, "A long list")))

    assert message["row_count"] == 500 and len(message["rows"]) == 200
    assert message["chart"]["type"] == "scatter" and message["chart"]["partial"] is True
    download = boss.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message['id']}/csv")
    assert len(download.text.splitlines()) == 501  # header + every row, not just the preview


def test_a_chart_can_be_edited_and_edits_are_checked(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE_SQL), SqlPlan(action="decline", answer="No.")]))
    message = final(events(ask(boss, space_id, cid, "Revenue by region")))
    declined = final(events(ask(boss, space_id, conversation(boss, space_id), "Nothing?")))
    base = f"/spaces/{space_id}/conversations/{cid}/messages/{message['id']}/chart"

    pie = boss.put(base, json={"type": "pie", "x": "region", "y": ["revenue"], "title": " Mix "})
    assert pie.status_code == 200
    assert pie.json()["chart"] == {
        "type": "pie",
        "x": "region",
        "y": ["revenue"],
        "series": None,
        "title": "Mix",
        "partial": False,
    }
    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]
    assert saved["chart"]["type"] == "pie"
    wrong_column = boss.put(base, json={"type": "bar", "x": "nope", "y": ["revenue"]})
    assert (wrong_column.status_code, code(wrong_column)) == (400, "invalid_chart")
    not_numeric = boss.put(base, json={"type": "bar", "x": "region", "y": ["region"]})
    assert code(not_numeric) == "invalid_chart"
    assert (
        boss.put(base, json={"type": "radar", "x": "region", "y": ["revenue"]}).status_code == 422
    )
    nothing = boss.put(
        f"/spaces/{space_id}/conversations/{declined['id']}/messages/{declined['id']}/chart",
        json={"type": "bar", "x": "a", "y": ["b"]},
    )
    assert nothing.status_code == 404  # wrong conversation for that message


# ── Starting a conversation ──────────────────────────────────────────────────


def test_what_data_is_available_is_answered_from_the_tables(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    plan = SqlPlan(action="describe", answer="One table, sales, with one row per order.")
    use(api, FakeLLM(chat_sql=[plan]))

    message = final(events(ask(boss, space_id, cid, "What data is available for me to explore?")))

    assert (message["status"], message["sql"]) == ("answer", None)
    assert message["answer"] == "One table, sales, with one row per order."
    assert message["sources"] == [{"type": "table", "header": "sales"}]


def test_suggested_questions_come_from_the_spaces_examples(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    viewer = person(api, boss, "vera@example.com", "viewer")
    outsider = person(api, boss, "olga@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    assert viewer.get(f"/spaces/{space_id}/suggestions").json() == [
        "What data is available for me to explore?"
    ]
    for title, trusted in (("Orders per region?", False), ("Total revenue?", True)):
        boss.post(
            f"/spaces/{space_id}/knowledge",
            json={
                "kind": "example_sql",
                "title": title,
                "body": "SELECT count(*) FROM sales",
                "trusted": trusted,
            },
        )

    suggestions = viewer.get(f"/spaces/{space_id}/suggestions").json()

    assert suggestions == [
        "What data is available for me to explore?",
        "Total revenue?",  # trusted ones first
        "Orders per region?",
    ]
    assert outsider.get(f"/spaces/{space_id}/suggestions").status_code == 404


def test_members_can_search_the_space_for_tables_terms_and_documents(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    boss.post(f"/spaces/{space_id}/documents", files={"file": ("policy.md", POLICY.encode())})
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={"kind": "glossary", "title": "Active customer", "body": "Ordered in 90 days."},
    )
    boss.post(
        f"/spaces/{space_id}/knowledge",
        json={"kind": "instruction", "body": "Round money to two decimals."},
    )
    viewer = person(api, boss, "vera@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})

    returns = viewer.get(f"/spaces/{space_id}/discover", params={"q": "return window"}).json()
    terms = viewer.get(f"/spaces/{space_id}/discover", params={"q": "active customer"}).json()
    tables = viewer.get(f"/spaces/{space_id}/discover", params={"q": "sales table"}).json()

    assert any(h["type"] == "document" and "thirty days" in h["snippet"] for h in returns)
    assert any(h["type"] == "glossary" and h["title"] == "Active customer" for h in terms)
    assert any(h["type"] == "table" and h["title"] == "sales" for h in tables)
    everything = returns + terms + tables
    assert all(h["type"] != "instruction" for h in everything)
    assert len({(h["type"], h["title"]) for h in everything}) == len(
        {(h["type"], h["title"]) for h in everything}
    )
    assert viewer.get(f"/spaces/{space_id}/discover", params={"q": ""}).status_code == 422
