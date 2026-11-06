"""Pinned chats stay at the top, and a new chat gets a short title, not its whole question."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import pytest
from fastapi.testclient import TestClient
from test_chat import conversation, small_space
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.services.conversations import title_from


@pytest.mark.parametrize(
    ("question", "title"),
    [
        (
            "Prepare a workforce analysis using the available employee, department, manager "
            "records. Show current workforce size",
            "Prepare a workforce analysis",
        ),
        (
            "Compare all departments based on their average current salary.",
            "Compare all departments",
        ),
        ("Revenue by region?", "Revenue by region"),
        ("Hi", "Hi"),  # too short to cut
    ],
)
def test_a_title_is_the_first_clause_cut_at_a_word(question: str, title: str) -> None:
    assert title_from(question) == title


@pytest.mark.db
def test_a_pinned_chat_stays_above_newer_ones_until_it_is_unpinned(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    old = conversation(boss, space_id, "Old thread")
    new = conversation(boss, space_id, "New thread")
    url = f"/spaces/{space_id}/conversations"

    def order() -> list[str]:
        return [c["title"] for c in boss.get(url).json()]

    assert order() == ["New thread", "Old thread"]
    pinned = boss.patch(f"{url}/{old}", json={"pinned": True})
    assert pinned.status_code == 200 and pinned.json()["pinned"] is True
    assert pinned.json()["title"] == "Old thread"  # pinning does not rename
    assert order() == ["Old thread", "New thread"]

    renamed = boss.patch(f"{url}/{old}", json={"title": "Kept thread"}).json()
    assert renamed["pinned"] is True and renamed["title"] == "Kept thread"  # nor rename unpin

    assert boss.patch(f"{url}/{old}", json={"pinned": False}).json()["pinned"] is False
    assert order() == ["New thread", "Kept thread"]
    assert new


@pytest.mark.db
def test_a_change_needs_something_to_change_and_only_the_owner_can_make_it(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    mine = conversation(boss, space_id)
    other = person(api, boss, "olga@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{other.id}", json={"role": "editor"})
    url = f"/spaces/{space_id}/conversations/{mine}"

    assert boss.patch(url, json={}).status_code == 422
    stranger = other.patch(url, json={"pinned": True})
    assert (stranger.status_code, code(stranger)) == (404, "not_found")


def test_a_very_long_question_is_cut_at_a_word_with_an_ellipsis() -> None:
    title = title_from("word " * 40)

    assert title.endswith("…") and len(title) <= 60 and "wor…" not in title
