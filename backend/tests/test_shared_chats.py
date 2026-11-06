"""Sharing a chat read-only with a space, and branching a chat into a new one."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

pytestmark = pytest.mark.db

REVENUE = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"


def setup(api: TestClient) -> tuple[Any, Any, Any, str, str, list[dict]]:
    """An admin, two editors, and a space where the first editor has a chat with two answers."""
    boss = admin(api)
    space_id = small_space(boss)
    ann = person(api, boss, "ann@example.com", "editor")
    bob = person(api, boss, "bob@example.com", "editor")
    for who in (ann, bob):
        assert (
            boss.put(f"/spaces/{space_id}/members/{who.id}", json={"role": "editor"}).status_code
            == 200
        )
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE)]))
    cid = conversation(ann, space_id, "Revenue chat")
    answers = [final(events(ask(ann, space_id, cid, q))) for q in ("Revenue by region", "Again")]
    return boss, ann, bob, space_id, cid, answers


def test_a_chat_is_private_until_its_owner_shares_it(api: TestClient) -> None:
    _, ann, bob, space_id, cid, _ = setup(api)
    url = f"/spaces/{space_id}/conversations"

    assert bob.get(f"{url}/{cid}").status_code == 404
    assert bob.get(f"{url}/shared").json() == []

    assert ann.patch(f"{url}/{cid}", json={"shared": True}).json()["shared"] is True
    shared = bob.get(f"{url}/shared").json()
    assert [(c["title"], c["owner_name"]) for c in shared] == [("Revenue chat", "ann")]
    seen = bob.get(f"{url}/{cid}").json()
    assert seen["mine"] is False and seen["owner_name"] == "ann" and len(seen["messages"]) == 2
    assert ann.get(f"{url}/shared").json() == []  # your own are not listed as shared with you

    assert ann.patch(f"{url}/{cid}", json={"shared": False}).json()["shared"] is False
    assert bob.get(f"{url}/{cid}").status_code == 404


def test_a_shared_chat_can_be_read_but_not_changed_or_continued(api: TestClient) -> None:
    _, ann, bob, space_id, cid, answers = setup(api)
    url = f"/spaces/{space_id}/conversations/{cid}"
    ann.patch(url, json={"shared": True})

    assert bob.patch(url, json={"title": "Mine now"}).status_code == 404
    assert bob.patch(url, json={"shared": False}).status_code == 404
    assert bob.delete(url).status_code == 404
    asked = ask(bob, space_id, cid, "Add to someone else's chat")
    assert asked.status_code == 404
    assert (
        bob.put(f"{url}/messages/{answers[0]['id']}/feedback", json={"rating": "up"}).status_code
        == 404
    )


def test_someone_outside_the_space_can_not_read_a_shared_chat(api: TestClient) -> None:
    boss, ann, _, space_id, cid, _ = setup(api)
    outsider = person(api, boss, "olu@example.com", "editor")
    ann.patch(f"/spaces/{space_id}/conversations/{cid}", json={"shared": True})

    assert outsider.get(f"/spaces/{space_id}/conversations/{cid}").status_code == 404


def test_a_chat_can_be_branched_from_any_answer_into_a_chat_of_your_own(api: TestClient) -> None:
    _, ann, bob, space_id, cid, answers = setup(api)
    url = f"/spaces/{space_id}/conversations"
    ann.patch(f"{url}/{cid}", json={"shared": True})

    whole = bob.post(f"{url}/{cid}/fork", json={})
    first = bob.post(f"{url}/{cid}/fork", json={"message_id": answers[0]["id"]})

    assert whole.status_code == 201 and first.status_code == 201
    mine = bob.get(f"{url}/{whole.json()['id']}").json()
    assert (
        mine["mine"] is True
        and mine["title"] == "Revenue chat (branch)"
        and mine["shared"] is False
    )
    assert [m["question"] for m in mine["messages"]] == ["Revenue by region", "Again"]
    assert (
        mine["messages"][0]["rows"] == answers[0]["rows"] and mine["messages"][0]["sql"] == REVENUE
    )
    assert [m["question"] for m in bob.get(f"{url}/{first.json()['id']}").json()["messages"]] == [
        "Revenue by region"
    ]
    assert {c["id"] for c in bob.get(url).json()} == {whole.json()["id"], first.json()["id"]}
    # the branch is independent: the original is untouched and the new chat takes new questions
    use(api, FakeLLM(chat_sql=[sql_plan(REVENUE)]))
    more = final(events(ask(bob, space_id, whole.json()["id"], "And one more")))
    assert more["seq"] == 3
    assert len(ann.get(f"{url}/{cid}").json()["messages"]) == 2


def test_feedback_does_not_travel_with_a_branch(api: TestClient) -> None:
    _, ann, _, space_id, cid, answers = setup(api)
    url = f"/spaces/{space_id}/conversations"
    ann.put(
        f"{url}/{cid}/messages/{answers[0]['id']}/feedback", json={"rating": "down", "comment": "x"}
    )

    branch = ann.post(f"{url}/{cid}/fork", json={}).json()

    copied = ann.get(f"{url}/{branch['id']}").json()["messages"][0]
    assert copied["feedback"] is None and copied["feedback_comment"] is None


def test_forking_a_message_that_is_not_in_the_chat_is_refused(api: TestClient) -> None:
    _, ann, _, space_id, cid, _ = setup(api)
    other = conversation(ann, space_id)

    response = ann.post(
        f"/spaces/{space_id}/conversations/{other}/fork",
        json={"message_id": setup_message(ann, space_id, cid)},
    )

    assert response.status_code == 404


def setup_message(owner: Any, space_id: str, cid: str) -> str:
    return owner.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]["id"]


# ── Sharing and access rules do not mix ──────────────────────────────────────


def test_a_space_with_access_rules_does_not_allow_sharing(api: TestClient) -> None:
    boss, ann, _, space_id, cid, _ = setup(api)
    table = boss.get(f"/spaces/{space_id}/tables").json()[0]["id"]
    boss.post(
        f"/spaces/{space_id}/access-rules",
        json={
            "table_id": table,
            "kind": "hide_column",
            "column": "unit_price",
            "audience": "viewers",
        },
    )

    blocked = ann.patch(f"/spaces/{space_id}/conversations/{cid}", json={"shared": True})

    assert (blocked.status_code, code(blocked)) == (409, "sharing_blocked")


def test_adding_a_rule_ends_every_share_in_the_space(api: TestClient) -> None:
    boss, ann, bob, space_id, cid, _ = setup(api)
    url = f"/spaces/{space_id}/conversations"
    ann.patch(f"{url}/{cid}", json={"shared": True})
    assert bob.get(f"{url}/{cid}").status_code == 200
    table = boss.get(f"/spaces/{space_id}/tables").json()[0]["id"]

    boss.post(
        f"/spaces/{space_id}/access-rules",
        json={
            "table_id": table,
            "kind": "hide_column",
            "column": "unit_price",
            "audience": "viewers",
        },
    )

    assert bob.get(f"{url}/{cid}").status_code == 404
    assert bob.get(f"{url}/shared").json() == []
    assert ann.get(f"{url}/{cid}").json()["shared"] is False


def test_a_change_to_a_chat_needs_something_to_change(api: TestClient) -> None:
    _, ann, _, space_id, cid, _ = setup(api)

    assert ann.patch(f"/spaces/{space_id}/conversations/{cid}", json={}).status_code == 422
