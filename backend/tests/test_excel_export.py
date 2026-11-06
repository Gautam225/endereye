"""A result as an Excel workbook: the rows on one sheet, what the answer said on another."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from test_chat import FakeLLM, ask, conversation, events, final, new_space, sql_plan, use
from test_spaces import admin, api, code, data_dir, external, person  # noqa: F401

from app.services.conversations import to_xlsx


def test_the_workbook_has_the_rows_a_bold_header_and_an_about_sheet() -> None:
    data = to_xlsx(
        ["who", "amount"],
        [["ann", 10.5], ["=cmd", 3], [None, None]],
        [("Question", "How much?"), ("SQL", "SELECT 1")],
    )

    book = load_workbook(io.BytesIO(data))
    results, about = book["Results"], book["About"]
    assert [[c.value for c in row] for row in results.iter_rows()] == [
        ["who", "amount"],
        ["ann", 10.5],
        ["'=cmd", 3],  # never run as a formula
        [None, None],
    ]
    assert results["A1"].font.bold and results.freeze_panes == "A2"
    assert [[c.value for c in row] for row in about.iter_rows()] == [
        ["Question", "How much?"],
        ["SQL", "SELECT 1"],
    ]


@pytest.mark.db
def test_a_result_downloads_as_excel_with_the_answer_beside_it(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    boss.upload(space_id, "notes.csv", b"who,amount\nann,10\nbob,20\n")
    cid = conversation(boss, space_id, "Notes & totals")
    use(api, FakeLLM(chat_sql=[sql_plan("SELECT who, amount FROM notes ORDER BY who")]))
    message = final(events(ask(boss, space_id, cid, "Show the notes")))
    base = f"/spaces/{space_id}/conversations/{cid}/messages"

    response = boss.get(f"{base}/{message['id']}/xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="notes-totals.xlsx"' in response.headers["content-disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert [[c.value for c in r] for r in book["Results"].iter_rows()] == [
        ["who", "amount"],
        ["ann", 10],
        ["bob", 20],
    ]
    about = {r[0].value: r[1].value for r in book["About"].iter_rows()}
    assert about["Question"] == "Show the notes" and about["Rows"] == "2"
    assert about["SQL"].startswith("SELECT who, amount FROM notes")


@pytest.mark.db
def test_the_workbook_obeys_the_same_access_rules_as_everything_else(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    boss.upload(space_id, "notes.csv", b"who,secret\nann,s1\nbob,s2\n")
    viewer = person(api, boss, "vera@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    table = boss.get(f"/spaces/{space_id}/tables").json()[0]["id"]
    boss.post(
        f"/spaces/{space_id}/access-rules",
        json={
            "table_id": table,
            "kind": "row_filter",
            "expression": "who = 'ann'",
            "audience": "viewers",
        },
    )
    cid = conversation(viewer, space_id)
    use(api, FakeLLM(chat_sql=[sql_plan("SELECT who FROM notes")]))
    message = final(events(ask(viewer, space_id, cid, "Who is there?")))

    response = viewer.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message['id']}/xlsx")

    book = load_workbook(io.BytesIO(response.content))
    assert [[c.value for c in r] for r in book["Results"].iter_rows()] == [["who"], ["ann"]]


@pytest.mark.db
def test_an_answer_without_a_query_has_nothing_to_export(api: TestClient) -> None:
    from app.chat.prompts import SqlPlan

    boss = admin(api)
    space_id = new_space(boss)
    cid = conversation(boss, space_id)
    use(api, FakeLLM(chat_sql=[SqlPlan(action="decline", answer="No.")]))
    message = final(events(ask(boss, space_id, cid, "Anything?")))

    response = boss.get(f"/spaces/{space_id}/conversations/{cid}/messages/{message['id']}/xlsx")

    assert (response.status_code, code(response)) == (404, "not_found")
