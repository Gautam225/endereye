"""Parser bake-off: which converter turns PDFs with headings and tables into the best Markdown?

    python scripts/parser_bakeoff.py markitdown
    python scripts/parser_bakeoff.py docling      (needs `pip install docling`)

It builds two sample PDFs, converts them, and scores what matters for retrieval: are the
section headings kept as Markdown headings, and does every table row stay on one line with
its cells in order. Run it once per converter and compare; the winner is the project default
(see DOCUMENT_PARSER in .env.example).
"""

import sys
import tempfile
import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TIERS = [
    ["Tier", "Discount", "Minimum yearly spend", "Free shipping"],
    ["Bronze", "5%", "10000", "No"],
    ["Silver", "10%", "50000", "No"],
    ["Gold", "15%", "100000", "Yes"],
    ["Platinum", "25%", "500000", "Yes"],
]
REGIONS = [
    ["Region", "Manager", "Target", "Actual"],
    ["North", "Asha Rao", "1200", "1350"],
    ["South", "Ravi Nair", "900", "820"],
    ["East", "Mina Das", "700", "745"],
    ["West", "Omar Sheikh", "1500", "1610"],
]
HEADINGS = ["Sales Policy 2025", "Discounts", "Regional targets", "Returns"]
PROSE = (
    "Discounts apply from the second quarter and are reviewed every year by the finance team. "
    "A customer moves up a tier as soon as the yearly spend passes the minimum. "
)


def _table(rows: list[list[str]]) -> Table:
    table = Table(rows)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    return table


def make_pdf(path: Path) -> None:
    styles = getSampleStyleSheet()
    story = [
        Paragraph(HEADINGS[0], styles["Title"]),
        Paragraph(PROSE * 3, styles["BodyText"]),
        Paragraph(HEADINGS[1], styles["Heading1"]),
        Paragraph(
            "The tiers below decide the discount and the shipping terms.", styles["BodyText"]
        ),
        Spacer(1, 8),
        _table(TIERS),
        Spacer(1, 12),
        Paragraph(HEADINGS[2], styles["Heading1"]),
        Paragraph("Targets and results per region, in thousands.", styles["BodyText"]),
        Spacer(1, 8),
        _table(REGIONS),
        Paragraph(HEADINGS[3], styles["Heading1"]),
        Paragraph("Returns are accepted within thirty days of delivery. " * 4, styles["BodyText"]),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def convert(parser: str, path: Path) -> str:
    if parser == "markitdown":
        from markitdown import MarkItDown

        return MarkItDown().convert(str(path)).text_content
    if parser == "docling":
        from docling.document_converter import DocumentConverter

        return DocumentConverter().convert(str(path)).document.export_to_markdown()
    raise SystemExit(f"Unknown parser {parser!r}")


def score(markdown: str) -> dict[str, float]:
    lines = markdown.splitlines()
    headings = [line.lstrip("#").strip().lower() for line in lines if line.startswith("#")]
    found_headings = sum(any(h.lower() == x or h.lower() in x for x in headings) for h in HEADINGS)
    rows = TIERS + REGIONS
    kept = 0
    for row in rows:
        for line in lines:
            if "|" not in line:
                continue
            position = 0
            for cell in row:
                position = line.find(cell, position)
                if position < 0:
                    break
                position += len(cell)
            else:
                kept += 1
                break
    return {"headings": found_headings / len(HEADINGS), "table_rows": kept / len(rows)}


def main() -> None:
    parser = sys.argv[1] if len(sys.argv) > 1 else "markitdown"
    with tempfile.TemporaryDirectory() as folder:
        pdf = Path(folder) / "policy.pdf"
        make_pdf(pdf)
        started = time.perf_counter()
        markdown = convert(parser, pdf)
        seconds = time.perf_counter() - started
    result = score(markdown)
    print(
        f"{parser}: headings kept {result['headings']:.0%}, "
        f"table rows kept {result['table_rows']:.0%}, {seconds:.1f}s"
    )
    print("---- first 1200 characters ----")
    print(markdown[:1200])


if __name__ == "__main__":
    main()
