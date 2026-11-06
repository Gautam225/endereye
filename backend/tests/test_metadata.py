"""Profiles, descriptions, searchable values and joins, end to end (needs the test database)."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_spaces import SALES_CSV, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.llm.gateway import get_llm
from app.schemas.metadata import ColumnDraft, TableDraft

pytestmark = pytest.mark.db

ORDERS_CSV = b"order_id,customer_id,note\n1,10,a\n2,10,b\n3,11,c\n4,12,d\n"
CUSTOMERS_CSV = b"id,name\n10,Asha\n11,Ravi\n12,Mina\n13,Omar\n"


def columns_by_name(boss: Any, space_id: str, table: str) -> dict[str, Any]:
    tables = boss.get(f"/spaces/{space_id}/metadata").json()
    (found,) = [t for t in tables if t["name"] == table]
    return {c["name"]: c for c in found["columns"]}


def sales_space(boss: Any) -> tuple[str, str]:
    space_id = new_space(boss)
    table = boss.upload(space_id, "sales.csv", SALES_CSV).json()
    return space_id, table["id"]


def test_new_tables_are_profiled_straight_away(api: TestClient) -> None:
    boss = admin(api)
    space_id, _ = sales_space(boss)

    (table,) = boss.get(f"/spaces/{space_id}/metadata").json()

    assert table["profiled_at"] is not None and table["row_count"] == 3 and not table["stale"]
    columns = {c["name"]: c for c in table["columns"]}
    assert list(columns) == ["region", "amount", "sold_on"]  # in the file's order
    region = columns["region"]
    assert region["stats"]["distinct_count"] == 2
    assert region["stats"]["top_values"][0] == {"value": "GJ", "count": 2}
    assert (region["entity_matching"], region["indexed_values"]) == (True, 2)
    assert (columns["amount"]["entity_matching"], columns["amount"]["indexed_values"]) == (False, 0)


def test_values_are_found_despite_spelling_mistakes(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    boss.upload(space_id, "stores.csv", b"state\nGujarat\nKerala\nMaharashtra\nGujarat\n")

    close = boss.get(f"/spaces/{space_id}/values", params={"q": "Gujrat"}).json()
    part = boss.get(f"/spaces/{space_id}/values", params={"q": "mahar"}).json()
    none = boss.get(f"/spaces/{space_id}/values", params={"q": "Zanzibar"}).json()
    wildcard = boss.get(f"/spaces/{space_id}/values", params={"q": "%"}).json()

    assert [(m["table"], m["column"], m["value"]) for m in close] == [
        ("stores", "state", "Gujarat")
    ]
    assert [m["value"] for m in part] == ["Maharashtra"]
    assert none == [] and wildcard == []


def test_editing_descriptions_synonyms_and_hiding_are_saved(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)
    region = columns_by_name(boss, space_id, "sales")["region"]

    table = boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/metadata", json={"description": "  One sale  "}
    ).json()
    changed = boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/columns/{region['id']}",
        json={"description": "Sales region", "synonyms": [" state ", "State", "zone", ""]},
    ).json()

    assert table["description"] == "One sale"
    assert (changed["description"], changed["synonyms"]) == ("Sales region", ["state", "zone"])
    hidden = boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/columns/{region['id']}", json={"hidden": True}
    ).json()
    assert hidden["hidden"] is True
    assert boss.get(f"/spaces/{space_id}/values", params={"q": "GJ"}).json() == []  # not shown

    too_many = boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/columns/{region['id']}",
        json={"synonyms": [f"s{i}" for i in range(21)]},
    )
    assert too_many.status_code == 422


def test_profiling_again_keeps_what_editors_wrote(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)
    region = columns_by_name(boss, space_id, "sales")["region"]
    boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/columns/{region['id']}",
        json={"description": "Sales region", "synonyms": ["zone"], "hidden": True},
    )

    again = boss.post(f"/spaces/{space_id}/tables/{table_id}/profile").json()

    kept = {c["name"]: c for c in again["columns"]}["region"]
    assert kept["id"] == region["id"]
    assert (kept["description"], kept["synonyms"], kept["hidden"]) == (
        "Sales region",
        ["zone"],
        True,
    )
    assert kept["indexed_values"] == 2 and kept["stats"] is not None


def test_searchable_values_can_be_switched_off_and_on(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)
    columns = columns_by_name(boss, space_id, "sales")
    url = f"/spaces/{space_id}/tables/{table_id}/columns"

    off = boss.patch(f"{url}/{columns['region']['id']}", json={"entity_matching": False}).json()
    assert (off["entity_matching"], off["indexed_values"]) == (False, 0)
    assert boss.get(f"/spaces/{space_id}/values", params={"q": "GJ"}).json() == []

    on = boss.patch(f"{url}/{columns['region']['id']}", json={"entity_matching": True}).json()
    assert (on["entity_matching"], on["indexed_values"]) == (True, 2)

    unshared = boss.patch(f"{url}/{columns['region']['id']}", json={"share_values": False}).json()
    assert (unshared["share_values"], unshared["entity_matching"]) == (False, False)
    assert unshared["indexed_values"] == 0

    numbers = boss.patch(f"{url}/{columns['amount']['id']}", json={"entity_matching": True})
    assert (numbers.status_code, code(numbers)) == (400, "not_searchable")


def test_only_editors_change_metadata_and_outsiders_see_nothing(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)
    viewer = person(api, boss, "vera@example.com", "viewer")
    outsider = person(api, boss, "olga@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    region = columns_by_name(boss, space_id, "sales")["region"]

    assert viewer.get(f"/spaces/{space_id}/metadata").status_code == 200
    assert viewer.get(f"/spaces/{space_id}/values", params={"q": "GJ"}).status_code == 200
    base = f"/spaces/{space_id}/tables/{table_id}"
    assert viewer.patch(f"{base}/metadata", json={"description": "x"}).status_code == 403
    assert viewer.patch(f"{base}/columns/{region['id']}", json={"hidden": True}).status_code == 403
    assert viewer.post(f"{base}/profile").status_code == 403
    assert viewer.post(f"{base}/draft").status_code == 403
    assert viewer.post(f"/spaces/{space_id}/joins/detect").status_code == 403
    assert outsider.get(f"/spaces/{space_id}/metadata").status_code == 404
    assert outsider.get(f"/spaces/{space_id}/values", params={"q": "GJ"}).status_code == 404


def test_a_column_of_another_table_is_not_found(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)
    other = boss.upload(space_id, "orders.csv", ORDERS_CSV).json()["id"]
    note = columns_by_name(boss, space_id, "orders")["note"]

    response = boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/columns/{note['id']}", json={"hidden": True}
    )

    assert (response.status_code, other is not None) == (404, True)


def test_joins_are_detected_confirmed_edited_and_removed(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    orders = boss.upload(space_id, "orders.csv", ORDERS_CSV).json()
    customers = boss.upload(space_id, "customers.csv", CUSTOMERS_CSV).json()

    found = boss.post(f"/spaces/{space_id}/joins/detect").json()

    assert len(found) == 1
    join = found[0]
    assert (join["left_table"], join["left_column"]) == ("orders", "customer_id")
    assert (join["right_table"], join["right_column"]) == ("customers", "id")
    assert (join["relationship"], join["source"], join["confirmed"]) == (
        "many_to_one",
        "detected",
        False,
    )
    assert boss.post(f"/spaces/{space_id}/joins/detect").json() == []  # nothing new

    confirmed = boss.patch(f"/spaces/{space_id}/joins/{join['id']}", json={"confirmed": True})
    assert confirmed.json()["confirmed"] is True
    bad = boss.patch(f"/spaces/{space_id}/joins/{join['id']}", json={"left_column": "nope"})
    assert (bad.status_code, code(bad)) == (400, "unknown_column")
    duplicate = boss.post(
        f"/spaces/{space_id}/joins",
        json={
            "left_table_id": orders["id"],
            "left_column": "customer_id",
            "right_table_id": customers["id"],
            "right_column": "id",
            "relationship": "many_to_one",
        },
    )
    assert duplicate.status_code == 409
    manual = boss.post(
        f"/spaces/{space_id}/joins",
        json={
            "left_table_id": orders["id"],
            "left_column": "order_id",
            "right_table_id": customers["id"],
            "right_column": "id",
            "relationship": "one_to_one",
        },
    ).json()
    assert (manual["source"], manual["confirmed"]) == ("manual", True)
    same = boss.post(
        f"/spaces/{space_id}/joins",
        json={
            "left_table_id": orders["id"],
            "left_column": "order_id",
            "right_table_id": orders["id"],
            "right_column": "customer_id",
            "relationship": "many_to_one",
        },
    )
    assert code(same) == "join_same_table"

    assert boss.delete(f"/spaces/{space_id}/joins/{join['id']}").status_code == 204
    assert [j["id"] for j in boss.get(f"/spaces/{space_id}/joins").json()] == [manual["id"]]


def test_removing_a_table_removes_its_metadata_and_joins(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    orders = boss.upload(space_id, "orders.csv", ORDERS_CSV).json()
    boss.upload(space_id, "customers.csv", CUSTOMERS_CSV)
    boss.post(f"/spaces/{space_id}/joins/detect")

    assert boss.delete(f"/spaces/{space_id}/tables/{orders['id']}").status_code == 204

    assert boss.get(f"/spaces/{space_id}/joins").json() == []
    assert [t["name"] for t in boss.get(f"/spaces/{space_id}/metadata").json()] == ["customers"]


def test_a_new_delta_version_marks_the_table_stale_until_profiled_again(
    api: TestClient, external: Path
) -> None:
    deltalake = pytest.importorskip("deltalake")
    import pyarrow as pa

    boss = admin(api)
    space_id = new_space(boss)
    folder = external / "stock_delta"
    deltalake.write_deltalake(str(folder), pa.table({"sku": ["a", "b"]}))
    table = boss.post(f"/spaces/{space_id}/tables/delta", json={"path": str(folder)}).json()
    assert boss.get(f"/spaces/{space_id}/metadata").json()[0]["stale"] is False

    deltalake.write_deltalake(str(folder), pa.table({"sku": ["c"]}), mode="append")
    stale = boss.get(f"/spaces/{space_id}/metadata").json()[0]
    assert (stale["stale"], stale["row_count"]) == (True, 2)

    fresh = boss.post(f"/spaces/{space_id}/tables/{table['id']}/profile").json()
    assert (fresh["stale"], fresh["row_count"]) == (False, 3)


class FakeLLM:
    def __init__(self) -> None:
        self.seen: list[Any] = []

    async def complete_json(self, messages: Any, schema: Any, **kwargs: Any) -> tuple[Any, Any]:
        self.seen.append((messages, kwargs))
        draft = TableDraft(
            description=" One row per sale. ",
            columns=[
                ColumnDraft(
                    name="region", description=" Sales region ", synonyms=["state", "STATE"]
                ),
                ColumnDraft(name="made_up", description="not a column"),
                ColumnDraft(name="amount", description="x" * 400),
            ],
        )
        return draft, None


def test_ai_drafts_are_cleaned_and_never_saved(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)
    region = columns_by_name(boss, space_id, "sales")["region"]
    boss.patch(
        f"/spaces/{space_id}/tables/{table_id}/columns/{region['id']}", json={"share_values": False}
    )
    fake = FakeLLM()
    api.app.dependency_overrides[get_llm] = lambda: fake
    try:
        response = boss.post(f"/spaces/{space_id}/tables/{table_id}/draft")
    finally:
        api.app.dependency_overrides.clear()

    draft = response.json()
    assert draft["description"] == "One row per sale."
    assert [c["name"] for c in draft["columns"]] == ["region", "amount"]  # unknown one dropped
    assert draft["columns"][0] == {
        "name": "region",
        "description": "Sales region",
        "synonyms": ["state"],
    }
    assert len(draft["columns"][1]["description"]) == 250
    prompt = fake.seen[0][0][1]["content"]
    assert "GJ" not in prompt and "MH" not in prompt  # region's values are not shared
    assert fake.seen[0][1]["tier"] == "fast"
    saved = boss.get(f"/spaces/{space_id}/metadata").json()[0]
    assert (
        saved["description"] == ""
        and columns_by_name(boss, space_id, "sales")["region"]["description"] == ""
    )


def test_drafting_without_ai_keys_says_so(api: TestClient) -> None:
    boss = admin(api)
    space_id, table_id = sales_space(boss)

    response = boss.post(f"/spaces/{space_id}/tables/{table_id}/draft")

    assert (response.status_code, code(response)) == (503, "llm_not_configured")
