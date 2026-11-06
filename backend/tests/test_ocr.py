"""Reading pictures (OCR): scanned PDF pages, the words in charts, image files, and what is said
about pages that could not be read. The engine is the real one (it runs on the CPU, no network)."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from test_chat import FakeLLM, ask, conversation, events, final, use
from test_spaces import admin, api, data_dir, external  # noqa: F401

from app.chat.prompts import SqlPlan
from app.rag.ocr import OcrOptions
from app.rag.parsing import ParseError, read_document

TYPED = "Our company policies are kept in this handbook and reviewed every year by the board."
SCANNED = ["Refund policy:", "items may be returned within 14 days."]
CHART = ["Revenue by region", "West 4200", "East 3100"]


def picture(lines: list[str], size: tuple[int, int] = (1000, 420)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    for row, line in enumerate(lines):
        draw.text((40, 40 + row * 90), line, font=font, fill="black")
    return image


def png(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    picture(lines).save(buffer, "PNG")
    return buffer.getvalue()


def pdf_of(*pages: tuple[str | None, list[str] | None]) -> bytes:
    """A PDF whose pages each have some typed text and/or a picture of text."""
    buffer = io.BytesIO()
    sheet = canvas.Canvas(buffer, pagesize=(595, 842))
    for text, lines in pages:
        if text:
            sheet.drawString(60, 790, text)
        if lines:
            sheet.drawImage(ImageReader(picture(lines)), 30, 200, width=535, height=225)
        sheet.showPage()
    sheet.save()
    return buffer.getvalue()


def stored(tmp_path: Path, data: bytes, name: str = "scan.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def words(text: str) -> str:
    return " ".join(text.lower().split())


# ── Reading ──────────────────────────────────────────────────────────────────


def test_a_scanned_page_is_read_and_marked_as_read_from_a_picture(tmp_path: Path) -> None:
    path = stored(tmp_path, pdf_of((TYPED, None), (None, SCANNED)))

    reading = read_document(path, options=OcrOptions(True, 10))

    typed, scanned = reading.pages
    assert (typed.number, typed.ocr) == (1, False)
    assert (scanned.number, scanned.ocr) == (2, True)
    assert "refund" in words(scanned.markdown) and "14 days" in words(scanned.markdown)
    assert reading.unread == []


def test_a_chart_on_a_typed_page_adds_the_words_in_the_picture(tmp_path: Path) -> None:
    path = stored(tmp_path, pdf_of((TYPED, CHART)))

    [page] = read_document(path, options=OcrOptions(True, 10)).pages

    assert page.ocr and "handbook" in words(page.markdown)  # the typed text is kept
    # (The engine sometimes drops the space between words, so compare without spaces.)
    squashed = words(page.markdown).replace(" ", "")
    assert "west4200" in squashed and "east3100" in squashed


def test_pages_that_are_only_pictures_are_listed_when_ocr_is_off(tmp_path: Path) -> None:
    path = stored(tmp_path, pdf_of((TYPED, None), (None, SCANNED), (None, SCANNED)))

    reading = read_document(path, options=OcrOptions(False, 10))

    assert [p.number for p in reading.pages] == [1]
    assert reading.unread == [2, 3]


def test_pages_over_the_limit_are_listed_as_not_read(tmp_path: Path) -> None:
    path = stored(tmp_path, pdf_of((None, SCANNED), (None, SCANNED), (None, SCANNED)))

    reading = read_document(path, options=OcrOptions(True, 1))

    assert [p.number for p in reading.pages] == [1]
    assert reading.unread == [2, 3]


def test_a_document_of_only_scans_says_what_to_turn_on(tmp_path: Path) -> None:
    path = stored(tmp_path, pdf_of((None, SCANNED)))

    with pytest.raises(ParseError, match="DOCUMENT_OCR"):
        read_document(path, options=OcrOptions(False, 10))


def test_an_image_file_is_read_as_one_page(tmp_path: Path) -> None:
    path = stored(tmp_path, png(SCANNED), "photo.png")

    [page] = read_document(path, options=OcrOptions(True, 10)).pages

    assert (page.number, page.ocr) == (1, True) and "14 days" in words(page.markdown)
    with pytest.raises(ParseError, match="OCR"):
        read_document(path, options=OcrOptions(False, 10))


def test_a_picture_with_no_text_is_refused_with_a_reason(tmp_path: Path) -> None:
    blank = io.BytesIO()
    Image.new("RGB", (600, 300), "white").save(blank, "PNG")
    path = stored(tmp_path, blank.getvalue(), "blank.png")

    with pytest.raises(ParseError, match="No text could be read"):
        read_document(path, options=OcrOptions(True, 10))


# ── In a chat ────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_an_answer_from_a_scanned_page_cites_it_and_says_it_was_read_by_ocr(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = boss.post("/chat/general").json()["id"]
    cid = conversation(boss, space_id)
    base = f"/spaces/{space_id}/conversations/{cid}/documents"

    added = boss.post(
        base, files={"file": ("handbook.pdf", pdf_of((TYPED, None), (None, SCANNED)))}
    )
    assert added.status_code == 201, added.text
    document: dict[str, Any] = added.json()
    assert (document["status"], document["page_count"]) == ("ready", 2)
    assert (document["ocr_pages"], document["unread_pages"]) == ([2], [])

    use(
        api,
        FakeLLM(
            chat_sql=[SqlPlan(action="answer", answer="Items can be returned within 14 days [S1].")]
        ),
    )
    done = final(events(ask(boss, space_id, cid, "How many days do I have to return items?")))

    [cite] = done["citations"]
    assert (cite["page"], cite["ocr"], cite["cited"]) == (2, True, True)


@pytest.mark.db
def test_an_image_can_be_added_to_a_chat(api: TestClient) -> None:
    boss = admin(api)
    space_id = boss.post("/chat/general").json()["id"]
    cid = conversation(boss, space_id)

    added = boss.post(
        f"/spaces/{space_id}/conversations/{cid}/documents",
        files={"file": ("receipt.png", png(SCANNED))},
    )

    assert added.status_code == 201, added.text
    assert (added.json()["status"], added.json()["ocr_pages"]) == ("ready", [1])
    shown = boss.get(f"/documents/{added.json()['id']}/file")
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/png"
