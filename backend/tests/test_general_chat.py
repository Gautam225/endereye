"""The general chat, documents added inside one conversation, @mentions, and the streamed
thought process (needs the test database)."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_knowledge import POLICY
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.chat.prompts import SqlPlan
from app.services import conversations as conversations_service

pytestmark = pytest.mark.db

ZEBRA = b"# Zebra rules\n\nThe zebra rule says that stripes must be counted twice in every audit.\n"
GOOD = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
ANSWER = SqlPlan(action="answer", answer="Stripes are counted twice.")


def add_doc(who: Any, space_id: str, cid: str, name: str = "zebra.md", body: bytes = ZEBRA) -> Any:
    return who.post(
        f"/spaces/{space_id}/conversations/{cid}/documents", files={"file": (name, body)}
    )


def general(who: Any) -> str:
    response = who.post("/chat/general")
    assert response.status_code == 200, response.text
    return response.json()["id"]


# ── The general chat ─────────────────────────────────────────────────────────


def test_everyone_gets_their_own_general_chat_space_that_is_not_listed(api: TestClient) -> None:
    boss = admin(api)
    other = person(api, boss, "olga@example.com", "editor")
    new_space(boss, "Sales")

    first = boss.post("/chat/general").json()
    again = boss.post("/chat/general").json()
    theirs = other.post("/chat/general").json()

    assert first["id"] == again["id"] and first["id"] != theirs["id"]  # made once, per person
    assert (first["is_personal"], first["name"], first["table_count"]) == (True, "General chat", 0)
    assert [s["name"] for s in boss.get("/spaces").json()] == ["Sales"]  # not in any list
    assert other.get("/spaces").json() == []
    base = f"/spaces/{first['id']}"
    assert boss.patch(base, json={"name": "Mine"}).status_code == 403
    assert boss.delete(base).status_code == 403
    assert other.get(base).status_code == 404  # nobody else can open it


# ── Documents added in a chat ────────────────────────────────────────────────


def test_a_document_added_in_a_chat_is_used_in_that_chat_only(
    api: TestClient, data_dir: Path, sql: Any
) -> None:
    boss = admin(api)
    space_id = general(boss)
    first, second = conversation(boss, space_id), conversation(boss, space_id)

    added = add_doc(boss, space_id, first)

    assert added.status_code == 201, added.text
    body = added.json()
    assert (body["status"], body["mention"], body["conversation_id"]) == ("ready", "zebra", first)
    assert body["chunk_count"] > 0
    base = f"/spaces/{space_id}/conversations"
    assert [d["id"] for d in boss.get(f"{base}/{first}/documents").json()] == [body["id"]]
    assert boss.get(f"{base}/{second}/documents").json() == []
    assert boss.get(f"/spaces/{space_id}/documents").json() == []  # not a space document
    assert boss.get(f"/spaces/{space_id}/index").json()["chunks"].get("document", 0) == 0

    fake = FakeLLM(chat_sql=[ANSWER])
    use(api, fake)
    answered = final(events(ask(boss, space_id, first, "What does the zebra rule say?")))
    nothing = final(events(ask(boss, space_id, second, "What does the zebra rule say?")))

    assert (answered["status"], answered["answer"]) == ("answer", "Stripes are counted twice.")
    assert "stripes must be counted twice" in fake.prompts("chat_sql")[0]
    assert "stripes must be counted twice" not in fake.prompts("chat_sql")[1]  # another chat
    # The general chat still replies; it just has no document to cite in the other chat.
    assert (nothing["status"], nothing["sources"]) == ("answer", [])

    assert sql("SELECT count(*) FROM chunks WHERE conversation_id = :c", {"c": first})[0][0] > 0
    stored = Path(sql("SELECT storage_path FROM documents")[0][0])
    assert stored.exists()
    assert boss.delete(f"{base}/{first}").status_code == 204
    assert sql("SELECT count(*) FROM documents")[0][0] == 0
    assert sql("SELECT count(*) FROM chunks WHERE conversation_id IS NOT NULL")[0][0] == 0
    assert not stored.exists()  # the file is removed with the chat


def test_viewers_can_add_documents_to_their_own_chats_and_others_cannot_see_them(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    viewer = person(api, boss, "vera@example.com", "viewer")
    peer = person(api, boss, "pat@example.com", "viewer")
    for who in (viewer, peer):
        boss.put(f"/spaces/{space_id}/members/{who.id}", json={"role": "viewer"})
    cid = conversation(viewer, space_id)

    added = add_doc(viewer, space_id, cid)

    assert added.status_code == 201
    doc = added.json()["id"]
    base = f"/spaces/{space_id}/conversations/{cid}/documents"
    for stranger in (peer, boss):
        assert stranger.get(base).status_code == 404
        assert add_doc(stranger, space_id, cid).status_code == 404
        assert stranger.delete(f"{base}/{doc}").status_code == 404
    assert boss.get(f"/spaces/{space_id}/documents").json() == []  # the space is unchanged
    assert viewer.delete(f"{base}/{doc}").status_code == 204
    assert viewer.get(base).json() == []


def test_chat_documents_are_checked_and_limited(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    monkeypatch.setattr(conversations_service, "MAX_CHAT_DOCUMENTS", 2)

    assert code(add_doc(boss, space_id, cid, "movie.mp4", b"1234")) == "file_type"
    assert add_doc(boss, space_id, cid, "empty.txt", b"").status_code == 400
    assert add_doc(boss, space_id, cid, "one.md").status_code == 201
    assert add_doc(boss, space_id, cid, "two.md").status_code == 201
    over = add_doc(boss, space_id, cid, "three.md")
    assert (over.status_code, code(over)) == (400, "too_many_documents")


# ── @mentions ────────────────────────────────────────────────────────────────


def test_mentioning_a_document_limits_the_answer_to_it(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    boss.post(f"/spaces/{space_id}/documents", files={"file": ("policy.md", POLICY.encode())})
    space_doc = boss.get(f"/spaces/{space_id}/documents").json()[0]
    cid = conversation(boss, space_id)
    mine = add_doc(boss, space_id, cid).json()
    fake = FakeLLM(chat_sql=[ANSWER, ANSWER])
    use(api, fake)

    pointed = final(
        events(ask(boss, space_id, cid, "What is the return window @zebra?", mentions=[mine["id"]]))
    )
    open_ = final(
        events(ask(boss, space_id, conversation(boss, space_id), "What is the return window?"))
    )

    assert pointed["mentions"] == [{"id": mine["id"], "name": "zebra", "kind": "document"}]
    only, anywhere = fake.prompts("chat_sql")
    assert "## Documents the user pointed at\n\nThe user mentioned: @zebra" in only
    assert "thirty days of delivery" not in only  # the space's policy was left out
    assert "stripes must be counted twice" in only
    assert "thirty days of delivery" in anywhere and "pointed at" not in anywhere
    assert open_["mentions"] == []
    assert space_doc["mention"] == "policy"


def test_a_mention_must_point_at_a_document_this_chat_can_use(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    first, second = conversation(boss, space_id), conversation(boss, space_id)
    theirs = add_doc(boss, space_id, first).json()
    use(api, FakeLLM(chat_sql=[ANSWER]))

    elsewhere = ask(boss, space_id, second, "About @zebra", mentions=[theirs["id"]])
    nothing = ask(
        boss, space_id, second, "About @x", mentions=["00000000-0000-0000-0000-000000000000"]
    )
    many = ask(boss, space_id, second, "x", mentions=[theirs["id"]] * 11)

    assert (elsewhere.status_code, nothing.status_code, many.status_code) == (404, 404, 422)
    assert boss.get(f"/spaces/{space_id}/conversations/{second}").json()["messages"] == []


# ── The thought process and the streamed answer ──────────────────────────────


def test_the_thought_process_and_answer_stream_in_pieces_and_are_saved(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    plan = sql_plan(GOOD, assumptions=["Used all dates."])
    use(
        api,
        FakeLLM(
            chat_sql=[plan],
            chat_explain=[
                __import__("test_chat").explanation("Across 4 regions, revenue is spread out.")
            ],
        ),
    )

    found = events(ask(boss, space_id, cid, "Revenue by region"))

    thoughts = [data for name, data in found if name == "thought"]
    assert [t["kind"] for t in thoughts] == ["step", "plan", "plan", "step"]
    assert thoughts[0]["text"].startswith("Looked through your space and found tables sales")
    assert thoughts[1]["text"] == "Group sales by region."
    assert thoughts[2]["text"] == "Assuming: Used all dates."
    assert thoughts[3]["text"].startswith("The query returned 4 rows in ")
    deltas = [data["text"] for name, data in found if name == "answer.delta"]
    full = next(data["text"] for name, data in found if name == "answer")
    assert len(deltas) > 1 and "".join(deltas) == full == "Across 4 regions, revenue is spread out."
    order = [name for name, _ in found]
    assert (
        order.index("thought")
        < order.index("sql")
        < order.index("answer.delta")
        < order.index("answer")
    )
    assert final(found)["thoughts"] == thoughts  # what was shown is what was saved
    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]
    assert saved["thoughts"] == thoughts


def test_a_repair_and_a_follow_up_show_up_in_the_thought_process(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid = conversation(boss, space_id)
    test_chat = __import__("test_chat")
    fake = FakeLLM(
        chat_sql=[sql_plan(GOOD), sql_plan("SELECT nothing FROM sales")],
        chat_repair=[sql_plan(GOOD)],
        chat_rewrite=[test_chat.rewrite("Revenue by region, only the east")],
    )
    use(api, fake)
    events(ask(boss, space_id, cid, "Revenue by region"))

    second = events(ask(boss, space_id, cid, "only the east"))

    texts = [d["text"] for n, d in second if n == "thought"]
    assert "Read your follow-up as: Revenue by region, only the east" in texts
    assert any(t.startswith("That query did not work (") for t in texts)
    kinds = [d["kind"] for n, d in second if n == "thought"]
    assert "note" in kinds


# ── Ordinary conversation in the general chat ────────────────────────────────


def test_the_general_chat_answers_ordinary_questions_without_any_data(api: TestClient) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    reply = "# SQL joins\n\nA join combines rows from two tables that share a value."
    fake = FakeLLM(chat_sql=[SqlPlan(action="chat", plan="A general question.", answer=reply)])
    use(api, fake)

    found = events(ask(boss, space_id, cid, "Explain how a SQL join works"))

    message = final(found)
    assert (message["status"], message["sql"], message["answer"]) == ("answer", None, reply)
    assert message["sources"] == []
    (prompt,) = fake.prompts("chat_sql")
    assert "friendly, knowledgeable assistant in a general chat" in prompt
    assert "careful data analyst" not in prompt
    deltas = [d["text"] for n, d in found if n == "answer.delta"]
    assert len(deltas) > 1 and "".join(deltas) == reply
    texts = [d["text"] for n, d in found if n == "thought"]
    assert texts == ["A general question."]  # no "looked through your space" for an empty space


def test_the_general_chat_answers_from_a_document_when_one_is_attached(api: TestClient) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_doc(boss, space_id, cid)
    use(api, FakeLLM(chat_sql=[ANSWER]))

    found = events(ask(boss, space_id, cid, "What does the zebra rule say?"))

    message = final(found)
    assert (message["status"], message["answer"]) == ("answer", "Stripes are counted twice.")
    assert any(s["type"] == "document" for s in message["sources"])
    first = next(d["text"] for n, d in found if n == "thought")
    assert first.startswith("Looked through your documents and found ")


def test_a_space_points_ordinary_questions_to_the_general_chat(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    use(api, FakeLLM(chat_sql=[SqlPlan(action="chat", answer="Paris.")]))

    message = final(
        events(ask(boss, space_id, conversation(boss, space_id), "What is the capital of France?"))
    )

    assert message["status"] == "declined"
    assert "general chat" in message["answer"] and "Paris" not in message["answer"]


# ── Charts from documents ────────────────────────────────────────────────────

CRESTVIEW = (
    b"# Crestview offer\n\nCrestview charges 40,000 per year and guarantees 99.5 percent uptime.\n"
)

TENDERS = (
    b"# Service levels\n\nSilverline guarantees 98 percent uptime and a 4 hour response. "
    b"Crestview guarantees 99.5 percent uptime and a 2 hour response.\n"
)


def test_a_graph_of_a_document_is_drawn_from_its_numbers_and_invented_ones_are_refused(
    api: TestClient,
) -> None:
    from app.chat.prompts import ChartSeries, DocChart

    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_doc(boss, space_id, cid, "tenders.md", TENDERS)
    real = DocChart(
        type="bar",
        title="Uptime guarantee",
        x_label="Vendor",
        y_label="Percent",
        labels=["Silverline", "Crestview"],
        series=[ChartSeries(name="Uptime (%)", values=[98, 99.5])],
        key_points=["Crestview promises 99.5%, Silverline 98%."],
    )
    made_up = DocChart(
        title="Customer satisfaction",
        labels=["Silverline", "Crestview"],
        series=[ChartSeries(name="Score", values=[4.1, 4.7])],
    )
    plan = SqlPlan(
        action="answer",
        answer="Crestview promises slightly higher uptime.",
        charts=[real, made_up],
    )
    use(api, FakeLLM(chat_sql=[plan]))

    found = events(ask(boss, space_id, cid, "make a graph for this doc"))

    message = final(found)
    figures = [data for name, data in found if name == "figure"]
    assert len(figures) == 1 and message["figures"] == figures
    assert figures[0]["title"] == "Uptime guarantee"
    assert figures[0]["series"] == [{"name": "Uptime (%)", "values": [98, 99.5]}]
    assert figures[0]["key_points"] == ["Crestview promises 99.5%, Silverline 98%."]
    notes = [d["text"] for n, d in found if n == "thought" and d["kind"] == "note"]
    assert notes == [
        'Left out the chart "Customer satisfaction": '
        "these values are not in the documents: 4.1, 4.7."
    ]
    order = [name for name, _ in found]
    assert order.index("answer") < order.index("figure") < order.index("done")
    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]
    assert saved["figures"] == figures


def test_chart_data_the_model_wrote_in_its_reply_is_drawn_as_a_chart(api: TestClient) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_doc(boss, space_id, cid, "tenders.md", TENDERS)
    pasted = (
        '{"type": "bar", "title": "Uptime guarantee", "labels": ["Silverline", "Crestview"], '
        '"series": [{"name": "Uptime (%)", "values": [98, 99.5]}]}'
    )
    reply = f"Crestview promises more uptime.\n```json\n{pasted}\n```"
    use(api, FakeLLM(chat_sql=[SqlPlan(action="answer", answer=reply)]))

    found = events(ask(boss, space_id, cid, "graph the uptime"))

    message = final(found)
    assert message["answer"] == "Crestview promises more uptime."
    assert [f["title"] for f in message["figures"]] == ["Uptime guarantee"]


def test_each_document_counts_once_as_a_source_and_both_are_read(api: TestClient) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_doc(boss, space_id, cid, "silverline.md", TENDERS)
    add_doc(
        boss,
        space_id,
        cid,
        "crestview.md",
        CRESTVIEW,
    )
    llm = FakeLLM(chat_sql=[ANSWER])
    use(api, llm)

    found = events(ask(boss, space_id, cid, "compare the uptime of both documents"))

    message = final(found)
    titles = [s["header"] for s in message["sources"] if s["type"] == "document"]
    assert sorted(titles) == ["crestview", "silverline"]  # one entry per document
    assert all(s["passages"] >= 1 for s in message["sources"])
    (prompt,) = llm.prompts("chat_sql")
    assert "40,000 per year" in prompt and "98 percent uptime" in prompt  # both are in the prompt


def _budget_chart(values: list[float], title: str = "Budget"):
    from app.chat.prompts import ChartSeries, DocChart

    return DocChart(
        title=title,
        labels=["Silverline", "Crestview"],
        series=[ChartSeries(name="Budget", values=values)],
    )


BUDGETS = (
    b"# Budgets" + bytes([10, 10]) + b"Silverline total approved budget is USD 7,900,000. "
    b"Crestview total approved budget is USD 3,150,000." + bytes([10])
)


def test_a_refused_chart_is_redrawn_once_and_shown(api: TestClient) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_doc(boss, space_id, cid, "budgets.md", BUDGETS)
    first = SqlPlan(
        action="answer",
        answer="Chart (See chart data in the JSON payload)",
        charts=[_budget_chart([79, 3.9])],
    )
    fixed = SqlPlan(
        action="answer",
        answer="Silverline's budget is higher.",
        charts=[_budget_chart([7900000, 3150000])],
    )
    llm = FakeLLM(chat_sql=[first], chat_repair=[fixed])
    use(api, llm)

    found = events(ask(boss, space_id, cid, "graph the budgets of both documents"))

    message = final(found)
    assert message["answer"] == "Silverline's budget is higher."
    assert [f["series"][0]["values"] for f in message["figures"]] == [[7900000, 3150000]]
    assert llm.purposes().count("chat_repair") == 1


def test_a_chart_that_cannot_be_drawn_is_explained_in_the_answer_not_hidden(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_doc(boss, space_id, cid, "budgets.md", BUDGETS)
    bad = SqlPlan(
        action="answer",
        answer="Silverline spends more. (See chart data in the JSON payload)",
        charts=[_budget_chart([1.3, 2.2])],
    )
    use(api, FakeLLM(chat_sql=[bad], chat_repair=[bad]))

    message = final(events(ask(boss, space_id, cid, "graph the budgets of both documents")))

    assert message["figures"] == []
    assert "JSON payload" not in message["answer"]
    assert "I couldn't draw the chart" in message["answer"] and "1.3, 2.2" in message["answer"]
