"""Page-level citations, the files behind them, and chats shared with chosen people (needs the
test database for most of it)."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import io
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from test_chat import FakeLLM, ask, conversation, events, final, use
from test_spaces import admin, api, data_dir, external, new_space, person  # noqa: F401

from app.chat.prompts import SqlPlan
from app.rag.parsing import Page, _slides, parse_pages

PAGES = [
    "The company was founded in Pune in 2009 and sells garden tools.",
    "Refund policy: customers may return unused items within 14 days for a full refund.",
    "Shipping takes five working days anywhere inside India.",
]
QUESTION = "How many days do customers have to return items for a refund?"


def make_pdf(pages: list[str] = PAGES) -> bytes:
    buffer = io.BytesIO()
    sheet = canvas.Canvas(buffer)
    for text in pages:
        sheet.drawString(72, 720, text)
        sheet.showPage()
    sheet.save()
    return buffer.getvalue()


def general(who: Any) -> str:
    return who.post("/chat/general").json()["id"]


def add_pdf(who: Any, space_id: str, cid: str) -> dict[str, Any]:
    added = who.post(
        f"/spaces/{space_id}/conversations/{cid}/documents",
        files={"file": ("policy.pdf", make_pdf())},
    )
    assert added.status_code == 201, added.text
    return added.json()


# ── Reading pages ────────────────────────────────────────────────────────────


def test_a_pdf_is_read_page_by_page_with_its_own_numbers(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    path.write_bytes(make_pdf(["First page text.", "", "Third page text."]))

    pages = parse_pages(path)

    assert [p.number for p in pages] == [1, 3]  # the blank page is skipped, not renumbered
    assert "Third page text." in pages[1].markdown


def test_a_deck_is_split_into_slides() -> None:
    markdown = "intro\n\n<!-- Slide number: 1 -->\n# Plan\n\n<!-- Slide number: 2 -->\n# Budget\n"
    pages = _slides(markdown)
    assert [(p.number, p.markdown.strip()) for p in pages] == [
        (None, "intro"),
        (1, "# Plan"),
        (2, "# Budget"),
    ]
    assert _slides("no slides here") == [Page(None, "no slides here")]


# ── Citations in an answer ───────────────────────────────────────────────────


def cited_answer(api: TestClient, who: Any) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    space_id = general(who)
    cid = conversation(who, space_id)
    document = add_pdf(who, space_id, cid)
    assert document["page_count"] == 3
    use(
        api,
        FakeLLM(
            chat_sql=[SqlPlan(action="answer", answer="Items can be returned within 14 days [S1].")]
        ),
    )
    done = final(events(ask(who, space_id, cid, QUESTION)))
    return space_id, cid, document, done


@pytest.mark.db
def test_an_answer_names_the_page_it_rests_on(api: TestClient) -> None:
    boss = admin(api)
    _, _cid, document, done = cited_answer(api, boss)

    assert done["status"] == "answer"
    [cite] = done["citations"]
    assert (cite["tag"], cite["page"], cite["cited"]) == ("S1", 2, True)
    assert cite["document_id"] == document["id"] and cite["title"] == "policy"
    assert "14 days" in cite["text"]


@pytest.mark.db
def test_a_passage_the_answer_did_not_cite_is_marked_as_only_found(api: TestClient) -> None:
    boss = admin(api)
    space_id = general(boss)
    cid = conversation(boss, space_id)
    add_pdf(boss, space_id, cid)
    use(api, FakeLLM(chat_sql=[SqlPlan(action="answer", answer="Within 14 days.")]))

    done = final(events(ask(boss, space_id, cid, QUESTION)))

    assert done["citations"] and not any(c["cited"] for c in done["citations"])


@pytest.mark.db
def test_the_original_file_opens_for_the_owner_only(api: TestClient) -> None:
    boss = admin(api)
    other = person(api, boss, "olga@example.com", "editor")
    _, _, document, _ = cited_answer(api, boss)

    mine = boss.get(f"/documents/{document['id']}/file")
    assert mine.status_code == 200 and mine.headers["content-type"] == "application/pdf"
    assert mine.content.startswith(b"%PDF")
    assert other.get(f"/documents/{document['id']}/file").status_code == 404
    assert boss.get("/documents/00000000-0000-0000-0000-000000000000/file").status_code == 404


# ── Sharing with chosen people ───────────────────────────────────────────────


@pytest.mark.db
def test_a_general_chat_shared_with_chosen_people_is_theirs_to_read(
    api: TestClient, sql: Any
) -> None:
    boss = admin(api)
    olga = person(api, boss, "olga@example.com", "viewer")
    stranger = person(api, boss, "sam@example.com", "viewer")
    space_id, cid, document, _ = cited_answer(api, boss)
    base = f"/spaces/{space_id}/conversations/{cid}/shares"

    assert boss.get(base).json() == {"people": [], "everyone": False}
    assert olga.get(f"/shared-chats/{cid}").status_code == 404  # not yet

    shared = boss.put(base, json={"user_ids": [olga.id]})
    assert shared.status_code == 200
    assert [p["full_name"] for p in shared.json()["people"]] == ["olga"]
    assert shared.json()["people"][0]["seen_at"] is None

    # She is told, finds it in her inbox as new, and opening it marks it seen.
    pending = olga.get("/notifications/pending").json()
    assert any(n["kind"] == "chat_shared" and n["link"] == f"/shared/{cid}" for n in pending)
    inbox = olga.get("/shared-chats").json()
    assert [(i["id"], i["unread"], i["personal"]) for i in inbox] == [(cid, True, True)]
    assert olga.get("/shared-chats/unread").json() == {"count": 1}
    opened = olga.get(f"/shared-chats/{cid}")
    assert opened.status_code == 200 and opened.json()["mine"] is False
    assert opened.json()["messages"][0]["citations"][0]["page"] == 2
    assert olga.get("/shared-chats/unread").json() == {"count": 0}
    assert boss.get(base).json()["people"][0]["seen_at"] is not None

    # What the chat cites opens for her; nobody else gets in.
    assert olga.get(f"/documents/{document['id']}/file").status_code == 200
    assert [d["id"] for d in olga.get(f"/shared-chats/{cid}/documents").json()] == [document["id"]]
    assert stranger.get(f"/shared-chats/{cid}").status_code == 404
    assert stranger.get(f"/documents/{document['id']}/file").status_code == 404

    # She can branch a copy of her own, which carries the citations.
    copy = olga.post(f"/shared-chats/{cid}/branch")
    assert copy.status_code == 200 and copy.json()["title"].endswith("(branch)")
    mine = olga.get(f"/spaces/{copy.json()['space_id']}/conversations/{copy.json()['id']}")
    assert mine.status_code == 200 and mine.json()["messages"][0]["citations"][0]["page"] == 2

    # Taking her off removes it all.
    assert boss.put(base, json={"user_ids": []}).json()["people"] == []
    assert olga.get(f"/shared-chats/{cid}").status_code == 404
    assert olga.get(f"/documents/{document['id']}/file").status_code == 404
    assert olga.get("/shared-chats").json() == []


@pytest.mark.db
def test_only_the_owner_chooses_who_a_chat_is_shared_with(api: TestClient) -> None:
    boss = admin(api)
    olga = person(api, boss, "olga@example.com", "viewer")
    space_id = general(boss)
    cid = conversation(boss, space_id)
    base = f"/spaces/{space_id}/conversations/{cid}/shares"

    assert olga.put(base, json={"user_ids": [olga.id]}).status_code == 404
    assert (
        boss.put(base, json={"user_ids": ["00000000-0000-0000-0000-000000000000"]}).status_code
        == 404
    )
    assert boss.put(base, json={"user_ids": [boss.id]}).json()["people"] == []  # not with yourself


@pytest.mark.db
def test_people_are_found_by_name_or_email(api: TestClient) -> None:
    boss = admin(api)
    olga = person(api, boss, "olga@example.com", "viewer")
    person(api, boss, "sam@example.com", "viewer")

    assert [p["email"] for p in olga.get("/people", params={"q": "SAM"}).json()] == [
        "sam@example.com"
    ]
    everyone = [p["email"] for p in olga.get("/people").json()]
    assert "olga@example.com" not in everyone and "asha@example.com" in everyone


# ── The document library of a space ──────────────────────────────────────────


@pytest.mark.db
def test_the_library_lists_pages_and_who_added_a_file_and_lets_editors_manage_it(
    api: TestClient,
) -> None:
    boss = admin(api)
    viewer = person(api, boss, "vera@example.com", "viewer")
    space_id = new_space(boss)
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})
    base = f"/spaces/{space_id}/documents"

    added = boss.post(base, files={"file": ("policy.pdf", make_pdf())})
    assert added.status_code == 201, added.text
    [listed] = viewer.get(base).json()
    assert (listed["page_count"], listed["uploaded_by"], listed["status"]) == (
        3,
        "Asha Admin",
        "ready",
    )

    # Anyone in the space can open the file; only editors change the library.
    assert viewer.get(f"/documents/{listed['id']}/file").status_code == 200
    assert viewer.patch(f"{base}/{listed['id']}", json={"title": "x"}).status_code == 403
    assert viewer.post(f"{base}/{listed['id']}/reread").status_code == 403

    renamed = boss.patch(f"{base}/{listed['id']}", json={"title": "Refund policy"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Refund policy"
    assert boss.patch(f"{base}/{listed['id']}", json={"title": "  "}).status_code == 422

    again = boss.post(f"{base}/{listed['id']}/reread")
    assert again.status_code == 200 and again.json()["status"] == "processing"


@pytest.mark.db
def test_a_renamed_document_is_cited_under_its_new_title(api: TestClient) -> None:
    boss = admin(api)
    space_id = new_space(boss)
    base = f"/spaces/{space_id}/documents"
    document = boss.post(base, files={"file": ("policy.pdf", make_pdf())}).json()
    boss.patch(f"{base}/{document['id']}", json={"title": "Refund policy"})
    for _ in range(100):  # the index is rebuilt in the background
        if boss.get(base).json()[0]["status"] == "ready":
            break
        time.sleep(0.1)
    use(api, FakeLLM(chat_sql=[SqlPlan(action="answer", answer="Within 14 days [S1].")]))
    cid = conversation(boss, space_id)

    done = final(events(ask(boss, space_id, cid, QUESTION)))

    assert [(c["title"], c["page"]) for c in done["citations"]] == [("Refund policy", 2)]


def test_citation_tags_are_found_in_every_form_models_write_them() -> None:
    from app.chat.context import BuiltContext
    from app.chat.pipeline import _citations
    from app.chat.prompts import Context

    built = BuiltContext(Context(), [])
    built.citations = [{"tag": f"S{n}", "title": "t", "page": n, "text": "x"} for n in (1, 2, 3, 4)]

    cited = _citations(built, "Larger budget 【S3】. Strict rules [S1, S2]. Nothing about S4.")

    assert [(c["tag"], c["cited"]) for c in cited] == [("S1", True), ("S2", True), ("S3", True)]
