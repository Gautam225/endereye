"""Spaces, members, and data tables, end to end through the API (needs the test database)."""

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.db

ADMIN = {
    "full_name": "Asha Admin",
    "email": "asha@example.com",
    "password": "correct-horse-battery",
}
SALES_CSV = b"region,amount,sold_on\nGJ,120.5,2026-01-05\nMH,80,2026-01-06\nGJ,40,2026-02-01\n"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def external(tmp_path: Path) -> Path:
    """A folder outside DATA_DIR that LOCAL_DATA_ROOTS allows."""
    folder = tmp_path / "external"
    folder.mkdir()
    return folder


@pytest.fixture
def api(settings: Settings, clean_db: None, data_dir: Path, external: Path) -> Iterator[TestClient]:
    custom = settings.model_copy(
        update={"data_dir": data_dir, "local_data_roots": [str(external)], "max_upload_mb": 1}
    )
    with TestClient(create_app(custom)) as client:
        yield client


class Person:
    def __init__(self, api: TestClient, token: str, user_id: str) -> None:
        self.api, self.id = api, user_id
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.api.get(f"/api/v1{path}", headers=self.headers, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        response = self.api.post(f"/api/v1{path}", headers=self.headers, **kwargs)
        if path.endswith("/documents") and response.status_code == 201:
            response = self._finished_document(path, response)
        return response

    def _finished_document(self, path: str, response: Any) -> Any:
        """A document is read and indexed in the background after the upload. Tests that upload
        one want it finished, so wait and hand back the finished document in the response."""
        document = response.json()
        deadline = time.monotonic() + 60
        while document["status"] == "processing" and time.monotonic() < deadline:
            time.sleep(0.05)
            listed = self.get(path).json()
            document = next(d for d in listed if d["id"] == document["id"])
        response._content = json.dumps(document).encode()
        return response

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.api.put(f"/api/v1{path}", headers=self.headers, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.api.patch(f"/api/v1{path}", headers=self.headers, **kwargs)

    def delete(self, path: str) -> Any:
        return self.api.delete(f"/api/v1{path}", headers=self.headers)

    def upload(self, space_id: str, filename: str, content: bytes, name: str | None = None) -> Any:
        return self.post(
            f"/spaces/{space_id}/tables/upload",
            files={"file": (filename, content)},
            data={"name": name} if name else None,
        )


def admin(api: TestClient) -> Person:
    body = api.post("/api/v1/auth/setup", json=ADMIN).json()
    return Person(api, body["access_token"], body["user"]["id"])


def person(api: TestClient, boss: Person, email: str, role: str) -> Person:
    created = boss.post(
        "/users",
        json={
            "full_name": email.split("@")[0],
            "email": email,
            "role": role,
            "password": "a-good-password",
        },
    ).json()
    token = api.post(
        "/api/v1/auth/login", json={"email": email, "password": "a-good-password"}
    ).json()["access_token"]
    return Person(api, token, created["id"])


def new_space(owner: Person, name: str = "Sales") -> str:
    response = owner.post("/spaces", json={"name": name, "description": "Regional sales"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def code(response: Any) -> str:
    return response.json()["error"]["code"]


def test_space_lifecycle(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)

    listed = boss.get("/spaces").json()
    assert [(s["name"], s["my_role"], s["member_count"]) for s in listed] == [
        ("Sales", "editor", 1)
    ]
    renamed = boss.patch(f"/spaces/{space_id}", json={"name": "Sales India"}).json()
    assert renamed["name"] == "Sales India"

    assert boss.delete(f"/spaces/{space_id}").status_code == 204
    assert boss.get(f"/spaces/{space_id}").status_code == 404


def test_upload_a_csv_then_preview_and_query_it(api: TestClient, data_dir: Path) -> None:
    boss = admin(api)
    space_id = new_space(boss)

    response = boss.upload(space_id, "Sales 2026 (final).csv", SALES_CSV)

    assert response.status_code == 201, response.text
    table = response.json()
    assert table["name"] == "sales_2026_final"
    assert (table["source_type"], table["source_ref"], table["row_count"]) == (
        "upload",
        "Sales 2026 (final).csv",
        3,
    )
    assert [c["name"] for c in table["columns"]] == ["region", "amount", "sold_on"]
    stored = list((data_dir / "spaces" / space_id).glob("*.parquet"))
    assert len(stored) == 1 and not list((data_dir / "tmp").iterdir())  # raw upload removed

    preview = boss.get(f"/spaces/{space_id}/tables/{table['id']}/preview").json()
    assert preview["row_count"] == 3

    result = boss.post(
        f"/spaces/{space_id}/query",
        json={
            "sql": "SELECT region, sum(amount) AS total FROM sales_2026_final GROUP BY 1 ORDER BY 1"
        },
    ).json()
    assert result["rows"] == [["GJ", 160.5], ["MH", 80.0]]
    assert [c["name"] for c in result["columns"]] == ["region", "total"]

    refused = boss.post(f"/spaces/{space_id}/query", json={"sql": "DROP TABLE sales_2026_final"})
    assert (refused.status_code, code(refused)) == (400, "sql_not_allowed")

    assert boss.delete(f"/spaces/{space_id}/tables/{table['id']}").status_code == 204
    assert not stored[0].exists()


def test_table_names_and_file_checks(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    assert boss.upload(space_id, "sales.csv", SALES_CSV).json()["name"] == "sales"
    assert boss.upload(space_id, "sales.csv", SALES_CSV).json()["name"] == "sales_2"
    assert boss.upload(space_id, "select.csv", SALES_CSV).json()["name"] == "select_data"

    taken = boss.upload(space_id, "x.csv", SALES_CSV, name="sales")
    assert (taken.status_code, code(taken)) == (409, "table_name_taken")
    bad_name = boss.upload(space_id, "x.csv", SALES_CSV, name="2 bad name")
    assert (bad_name.status_code, code(bad_name)) == (400, "table_name")
    wrong_type = boss.upload(space_id, "notes.pdf", b"%PDF-1.7")
    assert (wrong_type.status_code, code(wrong_type)) == (400, "file_type")
    empty = boss.upload(space_id, "empty.csv", b"")
    assert (empty.status_code, code(empty)) == (400, "file_empty")


def test_uploads_over_the_size_limit_are_refused(api: TestClient) -> None:
    boss = admin(api)
    limits = boss.get("/spaces/limits").json()
    assert limits["max_upload_mb"] == 1 and ".csv" in limits["file_types"]
    space_id = new_space(boss)
    too_big = b"a,b\n" + b"1,2\n" * (2 * 1024 * 1024 // 4)  # about 2 MB; the limit is 1 MB

    response = boss.upload(space_id, "big.csv", too_big)

    assert (response.status_code, code(response)) == (413, "file_too_large")


def test_delta_tables_by_folder(api: TestClient, external: Path, tmp_path: Path) -> None:
    deltalake = pytest.importorskip("deltalake")
    pa = pytest.importorskip("pyarrow")
    folder = external / "orders_delta"
    deltalake.write_deltalake(str(folder), pa.table({"id": [1, 2], "city": ["Surat", "Pune"]}))
    deltalake.write_deltalake(str(folder), pa.table({"id": [3], "city": ["Surat"]}), mode="append")
    boss = admin(api)
    space_id = new_space(boss)

    added = boss.post(f"/spaces/{space_id}/tables/delta", json={"path": str(folder)})

    assert added.status_code == 201, added.text
    table = added.json()
    assert (table["name"], table["row_count"], table["delta_version"]) == ("orders_delta", 3, 1)
    rows = boss.post(
        f"/spaces/{space_id}/query",
        json={"sql": "SELECT city, count(*) AS n FROM orders_delta GROUP BY 1 ORDER BY 1"},
    ).json()["rows"]
    assert rows == [["Pune", 1], ["Surat", 2]]

    outside = tmp_path / "elsewhere"
    deltalake.write_deltalake(str(outside), pa.table({"id": [1]}))
    refused = boss.post(f"/spaces/{space_id}/tables/delta", json={"path": str(outside)})
    assert (refused.status_code, code(refused)) == (403, "delta_path_not_allowed")
    not_delta = boss.post(f"/spaces/{space_id}/tables/delta", json={"path": str(external)})
    assert (not_delta.status_code, code(not_delta)) == (400, "delta_path")

    assert boss.delete(f"/spaces/{space_id}").status_code == 204
    assert (folder / "_delta_log").is_dir()  # someone else's Delta folder is never deleted


def test_who_can_see_and_change_a_space(api: TestClient) -> None:
    boss = admin(api)
    editor = person(api, boss, "erin@example.com", "editor")
    viewer = person(api, boss, "vik@example.com", "viewer")
    outsider = person(api, boss, "olu@example.com", "viewer")

    assert viewer.post("/spaces", json={"name": "Mine"}).status_code == 403
    space_id = new_space(editor)
    assert editor.upload(space_id, "sales.csv", SALES_CSV).status_code == 201

    assert outsider.get(f"/spaces/{space_id}").status_code == 404  # existence not revealed
    assert outsider.get("/spaces").json() == []

    # an editor of a space can not add people or change roles: only an administrator can
    for attempt in (
        editor.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"}),
        editor.put(f"/spaces/{space_id}/members/{editor.id}", json={"role": "editor"}),
        editor.delete(f"/spaces/{space_id}/members/{editor.id}"),
    ):
        assert (attempt.status_code, code(attempt)) == (403, "forbidden")
    assert (
        boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"}).status_code
        == 200
    )
    assert [s["my_role"] for s in viewer.get("/spaces").json()] == ["viewer"]
    table_id = viewer.get(f"/spaces/{space_id}/tables").json()[0]["id"]
    assert viewer.get(f"/spaces/{space_id}/tables/{table_id}/preview").status_code == 200
    for response in (
        viewer.upload(space_id, "more.csv", SALES_CSV),
        viewer.post(f"/spaces/{space_id}/query", json={"sql": "SELECT 1"}),
        viewer.delete(f"/spaces/{space_id}/tables/{table_id}"),
        viewer.put(f"/spaces/{space_id}/members/{outsider.id}", json={"role": "viewer"}),
    ):
        assert (response.status_code, code(response)) == (403, "forbidden")

    last = boss.put(f"/spaces/{space_id}/members/{editor.id}", json={"role": "viewer"})
    assert (last.status_code, code(last)) == (409, "last_editor")
    members = boss.get(f"/spaces/{space_id}/members").json()
    assert {(m["email"], m["role"]) for m in members} == {
        ("erin@example.com", "editor"),
        ("vik@example.com", "viewer"),
    }


def test_people_directory_is_for_admins_and_editors(api: TestClient) -> None:
    boss = admin(api)
    editor = person(api, boss, "erin@example.com", "editor")
    viewer = person(api, boss, "vik@example.com", "viewer")

    emails = [u["email"] for u in editor.get("/users/directory").json()]
    assert emails == ["asha@example.com", "erin@example.com", "vik@example.com"]
    assert viewer.get("/users/directory").status_code == 403
