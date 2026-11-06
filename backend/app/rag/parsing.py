"""Turning a document into Markdown (headings and tables kept), whatever its format.

Markdown and plain text are read as they are. PDF, Word, PowerPoint, Excel and HTML go through
the converter chosen by DOCUMENT_PARSER. Pictures are read with OCR (see `ocr.py`): scanned PDF
pages, the labels of charts on a page, and image files. Blocking: call from a worker thread.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import AppError
from app.rag import ocr
from app.rag.ocr import OcrOptions

logger = logging.getLogger(__name__)

TEXT_TYPES = {".md", ".markdown", ".txt"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
CONVERTED_TYPES = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}
DOCUMENT_TYPES = TEXT_TYPES | CONVERTED_TYPES | IMAGE_TYPES

# A page with less text than this and a picture over it is a scan. One with more text but a big
# picture (a chart, a diagram) has its picture read too, for the words and numbers in it.
MIN_PAGE_CHARS = 40
SCAN_PICTURE_SHARE = 0.10
FIGURE_PICTURE_SHARE = 0.15


class ParseError(AppError):
    status_code = 400
    code = "document_unreadable"


SLIDE = re.compile(r"<!--\s*Slide number:\s*(\d+)\s*-->")
NOT_WORD = re.compile(r"\W+")


@dataclass(frozen=True, slots=True)
class Page:
    """A stretch of a document that has its own number: a page of a PDF, a slide of a deck.
    `number` is None for formats that have no fixed pages (Word, HTML, text). `ocr` is set when
    the text (or part of it) was read from a picture, so it may hold mistakes."""

    number: int | None
    markdown: str
    ocr: bool = False


@dataclass(frozen=True, slots=True)
class Reading:
    """What was read from a document: its pages, and the pages that are pictures nothing could be
    read from (OCR turned off, not installed, over the limit, or an empty result)."""

    pages: list[Page]
    unread: list[int]


def parse_document(path: Path, parser: str = "markitdown", name: str | None = None) -> str:
    """`name` is what to call the file in error messages (the stored file has a random name)."""
    return "\n\n".join(page.markdown for page in parse_pages(path, parser, name))


def parse_pages(path: Path, parser: str = "markitdown", name: str | None = None) -> list[Page]:
    """The document's pages without OCR; see `read_document` for the full reading."""
    return read_document(path, parser, name, OcrOptions(enabled=False)).pages


def read_document(
    path: Path,
    parser: str = "markitdown",
    name: str | None = None,
    options: OcrOptions | None = None,
) -> Reading:
    """The document as Markdown, one entry per page or slide where the format has them, so an
    answer can say where in the file a passage came from. Blocking: call from a worker thread."""
    name = name or path.name
    options = options or OcrOptions()
    extension = path.suffix.lower()
    unread: list[int] = []
    pages: list[Page]
    if extension in TEXT_TYPES:
        pages = [Page(None, path.read_text(encoding="utf-8", errors="replace"))]
    elif extension in IMAGE_TYPES:
        pages = _picture(path, name, options)
    elif extension in CONVERTED_TYPES:
        try:
            if parser != "docling" and extension == ".pdf":
                pages, unread = _pdf_pages(path, options)
            else:
                pages = _convert(path, parser)
        except ParseError:
            raise
        except Exception as exc:
            first = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:300]
            raise ParseError(f"Could not read {name}: {first}") from None
    else:
        raise ParseError(f"This file type can't be read: {extension or 'no extension'}.")
    pages = [p for p in pages if p.markdown.strip()]
    if not pages:
        raise ParseError(_nothing_found(name, options))
    return Reading(pages, unread)


def _nothing_found(name: str, options: OcrOptions) -> str:
    if not options.enabled:
        return (
            f"No text was found in {name}. It looks like a scan, and reading pictures (OCR) is "
            "turned off: ask an administrator to set DOCUMENT_OCR=true."
        )
    if not ocr.available():
        return (
            f"No text was found in {name}. It looks like a scan, and the OCR engine could not "
            "start: ask an administrator to install rapidocr-onnxruntime."
        )
    return f"No text was found in {name}, even after reading its pictures."


def _convert(path: Path, parser: str) -> list[Page]:
    if parser == "docling":
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            raise ParseError(
                "DOCUMENT_PARSER is 'docling' but Docling is not installed (pip install docling)."
            ) from None
        return [Page(None, DocumentConverter().convert(str(path)).document.export_to_markdown())]

    from markitdown import MarkItDown

    markdown = MarkItDown().convert(str(path)).text_content
    if path.suffix.lower() == ".pptx":
        return _slides(markdown)
    return [Page(None, markdown)]


# ── Pictures ─────────────────────────────────────────────────────────────────


def _picture(path: Path, name: str, options: OcrOptions) -> list[Page]:
    """A photo or scan saved as an image file: one page, all of it read by OCR."""
    if not options.enabled:
        raise ParseError(
            f"{name} is a picture, and reading pictures (OCR) is turned off: ask an "
            "administrator to set DOCUMENT_OCR=true."
        )
    if not ocr.available():
        raise ParseError(
            f"{name} is a picture, and the OCR engine could not start: ask an administrator to "
            "install rapidocr-onnxruntime."
        )
    text = ocr.read_image_file(path)
    if not text.strip():
        raise ParseError(f"No text could be read in {name}.")
    return [Page(1, text.strip(), ocr=True)]


# ── PDF ──────────────────────────────────────────────────────────────────────


def _pdf_pages(path: Path, options: OcrOptions) -> tuple[list[Page], list[int]]:
    """One entry per page, with the page's own number (blank pages are skipped, not renumbered).
    Pages that look like forms or tables are read the way MarkItDown reads them (rows kept
    together); the rest are read as plain text, which spaces prose better. A scanned page is read
    with OCR; a page with a big picture on it also has the words in the picture added."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    tables = _table_pages(path)
    can_read_pictures = options.enabled and options.max_pages > 0 and ocr.available()
    budget = options.max_pages if can_read_pictures else 0
    pages: list[Page] = []
    unread: list[int] = []
    for number, layout in enumerate(extract_pages(str(path)), start=1):
        text = tables.get(number)
        if text is None:
            text = "".join(
                element.get_text() for element in layout if isinstance(element, LTTextContainer)
            )
        text = text.strip()
        share = _picture_share(layout)
        scanned = len(text) < MIN_PAGE_CHARS and share >= SCAN_PICTURE_SHARE
        figure = not scanned and share >= FIGURE_PICTURE_SHARE
        from_picture = ""
        if (scanned or figure) and budget > 0:
            budget -= 1
            from_picture = _read_pdf_page(path, number - 1)
        if scanned:
            text = f"{text}\n\n{from_picture}".strip() if text else from_picture
            if not from_picture:
                unread.append(number)
            if text:
                pages.append(Page(number, text, ocr=bool(from_picture)))
        elif figure and from_picture:
            extra = _new_lines(text, from_picture)
            pages.append(Page(number, f"{text}\n\n{extra}".strip(), ocr=bool(extra)))
        elif text:
            pages.append(Page(number, text))
    return pages, unread


def _read_pdf_page(path: Path, index: int) -> str:
    """The text of one page read from its picture; empty when it could not be (never raises:
    one bad page must not lose the rest of the document)."""
    try:
        return ocr.read_image(ocr.render_pdf_page(path, index)).strip()
    except Exception:
        logger.warning("OCR failed on page %d of a document", index + 1, exc_info=True)
        return ""


def _new_lines(text: str, from_picture: str) -> str:
    """The lines of a picture's text that the page's own text does not already say."""
    known = NOT_WORD.sub(" ", text.lower())
    fresh = []
    for line in from_picture.splitlines():
        plain = NOT_WORD.sub(" ", line.lower()).strip()
        if plain and plain not in known:
            fresh.append(line.strip())
    return "\n".join(fresh)


def _picture_share(layout: object) -> float:
    """How much of the page its pictures cover (0 to 1)."""
    from pdfminer.layout import LTFigure, LTImage

    area = float(getattr(layout, "width", 0) * getattr(layout, "height", 0)) or 1.0
    covered = 0.0

    def walk(items: object) -> None:
        nonlocal covered
        for element in items:  # type: ignore[attr-defined]
            if isinstance(element, LTImage):
                covered += max(element.width, 0.0) * max(element.height, 0.0)
            elif isinstance(element, LTFigure):
                walk(element)

    walk(layout)
    return min(1.0, covered / area)


def _table_pages(path: Path) -> dict[int, str]:
    """Page number -> Markdown, for the pages MarkItDown reads as forms or tables."""
    try:
        import pdfplumber
        from markitdown.converters._pdf_converter import _extract_form_content_from_words
    except ImportError:
        return {}
    found: dict[int, str] = {}
    try:
        with pdfplumber.open(str(path)) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                content = _extract_form_content_from_words(page)
                if content is not None:
                    found[number] = content
                page.close()
    except Exception:
        return {}
    return found


def _slides(markdown: str) -> list[Page]:
    """A deck as one page per slide, from the slide markers the converter writes."""
    parts = SLIDE.split(markdown)
    if len(parts) < 3:
        return [Page(None, markdown)]
    pages = [Page(None, parts[0])] if parts[0].strip() else []
    for number, body in zip(parts[1::2], parts[2::2], strict=True):
        pages.append(Page(int(number), body))
    return pages
