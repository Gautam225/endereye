"""Reading text out of pictures: scanned pages, photos of documents, and the labels of charts.

The engine is RapidOCR (ONNX models that ship inside the package), so it runs on this server, on
the CPU, and nothing is sent anywhere. It is loaded the first time it is needed. Blocking: call
from a worker thread.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# A line the engine is less sure of than this is dropped: a wrong number is worse than a gap.
MIN_CONFIDENCE = 0.55
RENDER_SCALE = 2.0  # PDF points to pixels: about 144 dpi, enough for ordinary print
MAX_SIDE = 3200  # larger renders are shrunk: they cost time and add nothing
_lock = threading.Lock()
_engine: Any = None
_failed = False


@dataclass(frozen=True, slots=True)
class OcrOptions:
    """Whether pictures are read, and how many pages of one document at most."""

    enabled: bool = True
    max_pages: int = 100


def available() -> bool:
    """True when the engine can be loaded (the packages are installed and the models load)."""
    return _load() is not None


def _load() -> Any:
    global _engine, _failed
    if _engine is not None or _failed:
        return _engine
    with _lock:
        if _engine is None and not _failed:
            try:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
            except Exception:
                logger.warning("OCR is not available", exc_info=True)
                _failed = True
    return _engine


def read_image(image: Any) -> str:
    """The text in a picture (an RGB array), one line of text per line, top to bottom."""
    engine = _load()
    if engine is None:
        return ""
    with _lock:  # one picture at a time: the engine is not built for several threads
        found, _ = engine(image)
    lines = [(box, text, float(score)) for box, text, score in (found or [])]
    kept = [
        (_top(box), _left(box), text.strip())
        for box, text, score in lines
        if score >= MIN_CONFIDENCE
    ]
    kept.sort(key=lambda item: (round(item[0] / 12), item[1]))  # rows of about one line
    return "\n".join(text for _, _, text in kept if text)


def _top(box: Any) -> float:
    return float(min(point[1] for point in box))


def _left(box: Any) -> float:
    return float(min(point[0] for point in box))


def render_pdf_page(path: Path, index: int) -> Any:
    """One page of a PDF as an RGB array (index counts from 0)."""
    import numpy
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    try:
        page = document[index]
        scale = min(RENDER_SCALE, MAX_SIDE / max(page.get_width(), page.get_height(), 1))
        picture = page.render(scale=scale).to_pil().convert("RGB")
        return numpy.array(picture)
    finally:
        document.close()


def read_image_file(path: Path) -> str:
    """The text of a photo or scan saved as an image file."""
    import numpy
    from PIL import Image

    with Image.open(path) as picture:
        picture = picture.convert("RGB")
        longest = max(picture.size)
        if longest > MAX_SIDE:
            ratio = MAX_SIDE / longest
            picture = picture.resize((round(picture.width * ratio), round(picture.height * ratio)))
        return read_image(numpy.array(picture))
