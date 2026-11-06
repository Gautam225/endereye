"""The shared metric layer: definitions with an owner, a version history and tests (needs the
test database). A change that breaks a test is refused unless the person says to save it anyway."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import small_space
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.services.expressions import metric_sql

pytestmark = pytest.mark.db


def test_the_number_a_test_looks_at_depends_on_the_kind_of_definition() -> None:
    assert (
        metric_sql("measure", "sum(amount)", "sales", None)
        == 'SELECT sum(amount) AS value FROM "sales"'
    )
    assert "WHERE (region = 'N')" in metric_sql("measure", "sum(amount)", "sales", "region = 'N'")
    assert metric_sql("filter", "amount > 5", "sales", "x = 1").endswith(
        "WHERE (amount > 5) AND (x = 1)"
    )
    assert "count(DISTINCT region)" in metric_sql("dimension", "region", "sales", None)


def metric(boss: Person, space_id: str, **extra: Any) -> Any:
    body = {"name": "Orders", "type": "measure", "expression": "count(*)", "table_name": "sales"}
    return boss.post(f"/spaces/{space_id}/expressions", json={**body, **extra})


def test_a_definition_has_an_owner_and_a_first_version(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)

    made = metric(boss, space_id)

    assert made.status_code == 201, made.text
    body = made.json()
    assert body["owner_id"] == boss.id and body["owner_name"] and body["version"] == 1
    versions = boss.get(f"/spaces/{space_id}/expressions/{body['id']}/versions").json()
    assert [(v["version"], v["note"]) for v in versions] == [(1, "Created")]


def test_every_change_to_the_definition_is_a_new_version_and_can_be_restored(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item = metric(boss, space_id).json()
    base = f"/spaces/{space_id}/expressions/{item['id']}"

    second = boss.patch(base, json={"description": "Orders placed", "note": "Explained it"}).json()
    same = boss.patch(base, json={"description": "Orders placed"}).json()  # nothing changed
    third = boss.patch(base, json={"expression": "count(order_id)"}).json()
    restored = boss.post(f"{base}/versions/1/restore", json={}).json()

    assert (second["version"], same["version"], third["version"]) == (2, 2, 3)
    assert restored["version"] == 4 and restored["expression"] == "count(*)"
    assert restored["description"] == ""
    versions = boss.get(f"{base}/versions").json()
    assert [v["version"] for v in versions] == [4, 3, 2, 1]
    assert versions[0]["note"] == "Restored version 1" and versions[2]["note"] == "Explained it"
    assert boss.post(f"{base}/versions/9/restore", json={}).status_code == 404


def test_a_change_that_breaks_a_test_is_refused_unless_accepted(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item = metric(boss, space_id).json()
    base = f"/spaces/{space_id}/expressions/{item['id']}"
    test = boss.post(f"{base}/tests", json={"name": "All 60 orders", "expected": 60})
    assert test.status_code == 201 and test.json()["last_status"] == "pass"

    refused = boss.patch(base, json={"expression": "count(*) - 1"})
    assert (refused.status_code, code(refused)) == (409, "tests_failed")
    assert "All 60 orders" in refused.text
    assert boss.get(f"{base}/versions").json()[0]["version"] == 1  # nothing was saved

    forced = boss.patch(base, json={"expression": "count(*) - 1", "accept_failing_tests": True})
    assert forced.json()["version"] == 2 and forced.json()["tests_failing"] == 1
    (shown,) = boss.get(f"{base}/tests").json()
    assert (
        shown["last_status"] == "fail" and shown["last_value"] == 59 and shown["last_version"] == 2
    )

    undone = boss.post(f"{base}/versions/1/restore", json={}).json()
    assert undone["tests_failing"] == 0 and undone["version"] == 3


def test_tests_can_narrow_the_rows_have_a_tolerance_and_can_be_run_and_removed(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item = metric(boss, space_id).json()
    base = f"/spaces/{space_id}/expressions/{item['id']}"

    near = boss.post(f"{base}/tests", json={"name": "About 60", "expected": 58, "tolerance": 2})
    narrowed = boss.post(
        f"{base}/tests", json={"name": "Nobody", "where_sql": "order_id < 0", "expected": 0}
    )
    wrong = boss.post(f"{base}/tests", json={"name": "Bad", "where_sql": "nope = 1", "expected": 1})

    assert near.json()["last_status"] == "pass" and narrowed.json()["last_status"] == "pass"
    assert wrong.status_code == 400  # a test that can't run is not kept
    ran = boss.post(f"{base}/tests/run").json()
    assert (ran["passed"], ran["failed"]) == (2, 0)
    overall = boss.post(f"/spaces/{space_id}/expressions/run-tests").json()
    assert overall["passed"] == 2 and {t["expression_id"] for t in overall["tests"]} == {item["id"]}

    fixed = boss.patch(f"{base}/tests/{near.json()['id']}", json={"expected": 10, "tolerance": 0})
    assert fixed.json()["last_status"] == "fail"
    assert boss.delete(f"{base}/tests/{near.json()['id']}").status_code == 204
    assert len(boss.get(f"{base}/tests").json()) == 1


def test_a_definition_without_a_table_cannot_have_tests(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item = metric(boss, space_id, name="Constant", expression="1 + 1", table_name=None).json()

    made = boss.post(
        f"/spaces/{space_id}/expressions/{item['id']}/tests", json={"name": "Two", "expected": 2}
    )

    assert made.status_code == 400


def test_the_owner_can_be_changed_to_someone_who_can_use_the_space(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item = metric(boss, space_id).json()
    base = f"/spaces/{space_id}/expressions/{item['id']}"
    editor = person(api, boss, "ed@example.com", "editor")
    stranger = person(api, boss, "st@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{editor.id}", json={"role": "editor"})

    assert boss.patch(base, json={"owner_id": stranger.id}).status_code == 400
    moved = boss.patch(base, json={"owner_id": editor.id}).json()

    assert moved["owner_id"] == editor.id and moved["owner_name"] == "ed"
    assert moved["version"] == 1  # who owns it is not part of the definition


def test_everyone_in_the_space_sees_the_definitions_but_only_editors_change_them(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    item = metric(boss, space_id).json()
    viewer = person(api, boss, "vi@example.com", "viewer")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    base = f"/spaces/{space_id}/expressions/{item['id']}"

    assert [e["name"] for e in viewer.get(f"/spaces/{space_id}/expressions").json()] == ["Orders"]
    assert viewer.get(f"{base}/versions").status_code == 200
    assert viewer.get(f"{base}/tests").status_code == 200
    assert viewer.patch(base, json={"description": "x"}).status_code == 403
    assert viewer.post(f"{base}/tests", json={"name": "t", "expected": 1}).status_code == 403
    assert viewer.post(f"{base}/versions/1/restore", json={}).status_code == 403
