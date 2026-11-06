"""Dashboards: kept answers that are refreshed by running their SQL again (needs the test
database). Each person's dashboard is private, and a refresh obeys that person's access rules."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import (
    REVENUE_SQL,
    FakeLLM,
    ask,
    conversation,
    events,
    final,
    small_space,
    sql_plan,
    use,
)
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

pytestmark = pytest.mark.db


def answered(boss: Person, space_id: str, sql: str = REVENUE_SQL) -> tuple[str, str]:
    """A saved answer to keep: the conversation and message ids."""
    use(boss.api, FakeLLM(chat_sql=[sql_plan(sql)]))
    cid = conversation(boss, space_id)
    message = final(events(ask(boss, space_id, cid, "Revenue by region?")))
    assert message["status"] == "ok"
    return cid, message["id"]


def pin(boss: Person, space_id: str, cid: str, mid: str, **extra: Any) -> Any:
    return boss.post(
        f"/spaces/{space_id}/dashboards/pin",
        json={"conversation_id": cid, "message_id": mid, **extra},
    )


def test_an_answer_is_kept_on_a_dashboard_and_refreshed_with_new_data(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)

    kept = pin(boss, space_id, cid, mid)

    assert kept.status_code == 201, kept.text
    item = kept.json()
    assert item["question"] == "Revenue by region?" and item["sql"] == REVENUE_SQL
    assert item["row_count"] == 4 and item["refresh_error"] == ""
    (dashboard,) = boss.get(f"/spaces/{space_id}/dashboards").json()
    assert dashboard["name"] == "My dashboard" and [i["id"] for i in dashboard["items"]] == [
        item["id"]
    ]

    assert boss.upload(space_id, "sales.csv", b"region,amount\nNorth,1\n").status_code in (201, 409)
    refreshed = boss.post(f"/spaces/{space_id}/dashboards/items/{item['id']}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshed_at"] is not None


def test_a_refresh_that_fails_keeps_the_old_result_and_says_why(api: TestClient, sql: Any) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()
    sql(
        "UPDATE dashboard_items SET sql = 'SELECT nope FROM sales' WHERE id = :i", {"i": item["id"]}
    )

    refreshed = boss.post(f"/spaces/{space_id}/dashboards/items/{item['id']}/refresh").json()

    assert refreshed["refresh_error"] and refreshed["row_count"] == 4  # the old result stays


def test_a_dashboard_is_private_to_its_owner(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    other = person(api, boss, "other@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{other.id}", json={"role": "viewer"})
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()
    dashboard_id = item["dashboard_id"]

    assert other.get(f"/spaces/{space_id}/dashboards").json() == []
    base = f"/spaces/{space_id}/dashboards"
    assert other.post(f"{base}/items/{item['id']}/refresh").status_code == 404
    assert other.delete(f"{base}/items/{item['id']}").status_code == 404
    assert other.post(f"{base}/{dashboard_id}/refresh").status_code == 404
    assert other.delete(f"{base}/{dashboard_id}").status_code == 404
    assert pin(other, space_id, cid, mid).status_code == 404  # not their chat


def test_only_an_answer_with_a_query_can_be_kept_and_a_dashboard_holds_a_limited_number(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)

    missing = pin(boss, space_id, cid, "00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404

    named = boss.post(f"/spaces/{space_id}/dashboards", json={"name": "Board"}).json()
    kept = pin(boss, space_id, cid, mid, dashboard_id=named["id"], title="Revenue")
    assert kept.json()["title"] == "Revenue" and kept.json()["dashboard_id"] == named["id"]

    renamed = boss.patch(f"/spaces/{space_id}/dashboards/{named['id']}", json={"name": "Sales"})
    assert renamed.json()["name"] == "Sales"
    moved = boss.patch(
        f"/spaces/{space_id}/dashboards/items/{kept.json()['id']}", json={"title": "Money"}
    )
    assert moved.json()["title"] == "Money"
    assert boss.delete(f"/spaces/{space_id}/dashboards/{named['id']}").status_code == 204
    assert boss.get(f"/spaces/{space_id}/dashboards").json() == []


def test_kept_answers_can_be_searched_and_paged_without_their_results(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    for title in ("Revenue West", "Revenue East", "Headcount"):
        assert pin(boss, space_id, cid, mid, title=title).status_code == 201
    other = person(api, boss, "other@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{other.id}", json={"role": "editor"})
    base = f"/spaces/{space_id}/dashboards/items"

    everything = boss.get(base).json()
    some = boss.get(base, params={"q": "west"}).json()
    narrow = boss.get(base, params={"q": "revenue west"}).json()
    page = boss.get(base, params={"limit": 2, "offset": 2}).json()

    assert everything["total"] == 3 and len(everything["items"]) == 3
    assert {"id", "title", "question", "dashboard_name"} == set(everything["items"][0])
    assert some["total"] == 1 and some["items"][0]["title"] == "Revenue West"
    assert narrow["total"] == 1  # every word has to match, in the title or the question
    assert page["total"] == 3 and len(page["items"]) == 1
    assert other.get(base).json() == {"total": 0, "items": []}  # only your own
    assert boss.get(base, params={"limit": 101}).status_code == 422
    assert boss.get(base, params={"q": "%"}).json()["total"] == 3  # not a wildcard
