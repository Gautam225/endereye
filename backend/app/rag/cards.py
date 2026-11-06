"""What gets indexed: schema cards, example questions, instructions, glossary terms, documents.

Pure functions: they turn plain data into `ChunkSpec`s (the text to embed and its metadata).
Storing and searching them is in app/services/indexing.py and app/rag/retrieval.py.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.rowcount import rows_text
from app.rag.chunking import Splitter
from app.rag.parsing import Page

MAX_COMMON_VALUES = 5


@dataclass(frozen=True, slots=True)
class ChunkSpec:
    source_type: str  # table, column, instruction, glossary, example_sql, document
    source_key: str  # "table:<id>", "column:<id>", "item:<id>" or "doc:<id>"
    position: int  # piece number within the source
    header: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n{self.text}"

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            [self.source_type, self.header, self.text, self.meta], sort_keys=True, default=str
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    id: str
    name: str
    type: str
    description: str = ""
    synonyms: tuple[str, ...] = ()
    hidden: bool = False
    share_values: bool = True
    stats: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TableInfo:
    id: str
    name: str
    description: str
    row_count: int  # -1 when not known
    columns: tuple[ColumnInfo, ...]
    approximate: bool = False


@dataclass(frozen=True, slots=True)
class JoinInfo:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    relationship: str


@dataclass(frozen=True, slots=True)
class ItemInfo:
    id: str
    kind: str  # instruction, glossary, example_sql
    title: str
    body: str
    trusted: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class ExpressionInfo:
    id: str
    name: str
    type: str  # measure, filter, dimension
    expression: str
    table_name: str | None = None
    description: str = ""
    synonyms: tuple[str, ...] = ()
    is_default: bool = False


def expression_chunks(items: Iterable[ExpressionInfo], splitter: Splitter) -> list[ChunkSpec]:
    """One chunk per business definition: found by its name, synonyms and description."""
    specs: list[ChunkSpec] = []
    for item in items:
        lines = [f"{item.type.capitalize()} {item.name}."]
        if item.description:
            lines.append(item.description)
        if item.synonyms:
            lines.append("Also called: " + ", ".join(item.synonyms) + ".")
        where = f" on table {item.table_name}" if item.table_name else ""
        lines.append(f"Defined{where} as: {item.expression}")
        meta = {
            "name": item.name,
            "kind": item.type,
            "sql": item.expression,
            "table": item.table_name,
            "default": item.is_default,
            "description": item.description,
        }
        specs += _pieces(
            "expression",
            f"expr:{item.id}",
            f"{item.type.capitalize()}: {item.name}",
            "\n".join(lines),
            splitter,
            meta,
        )
    return specs


def _plain_type(type_name: str) -> str:
    return type_name.lower()


def table_text(table: TableInfo, joins: Iterable[JoinInfo]) -> str:
    visible = [c for c in table.columns if not c.hidden]
    lines = [
        f"Table {table.name}: {table.description.strip() or 'no description.'}"
        + (f" It has {size}." if (size := rows_text(table.row_count, table.approximate)) else ""),
        "Columns: " + ", ".join(f"{c.name} ({_plain_type(c.type)})" for c in visible) + ".",
    ]
    related = [
        f"{j.left_table}.{j.left_column} = {j.right_table}.{j.right_column} "
        f"({j.relationship.replace('_', ' ')})"
        for j in joins
        if table.name in (j.left_table, j.right_table)
    ]
    if related:
        lines.append("Joins: " + "; ".join(related) + ".")
    return "\n".join(lines)


def column_text(table: TableInfo, column: ColumnInfo) -> str:
    lines = [f"Column {column.name} of table {table.name}, type {_plain_type(column.type)}."]
    if column.description.strip():
        lines.append(column.description.strip())
    if column.synonyms:
        lines.append("Also called: " + ", ".join(column.synonyms) + ".")
    stats = column.stats or {}
    if column.share_values:
        common = stats.get("top_values") or []
        if common:
            shown = ", ".join(f"{v['value']} ({v['count']:,})" for v in common[:MAX_COMMON_VALUES])
            lines.append(f"Common values: {shown}.")
        low, high = stats.get("min"), stats.get("max")
        if (
            low is not None
            and high is not None
            and low != high
            and column.type.upper() != "VARCHAR"
        ):
            lines.append(f"Ranges from {low} to {high}.")
    if stats.get("null_pct"):
        lines.append(f"{stats['null_pct']}% of values are empty.")
    return "\n".join(lines)


def schema_chunks(
    tables: Iterable[TableInfo], joins: Iterable[JoinInfo], splitter: Splitter
) -> list[ChunkSpec]:
    """One card per table and one per column. Hidden columns get no card."""
    joins = list(joins)
    specs: list[ChunkSpec] = []
    for table in tables:
        visible = [c for c in table.columns if not c.hidden]
        meta = {"table": table.name, "columns": [c.name for c in visible]}
        specs += _pieces(
            "table",
            f"table:{table.id}",
            f"Table {table.name}",
            table_text(table, joins),
            splitter,
            meta,
        )
        for column in visible:
            specs += _pieces(
                "column",
                f"column:{column.id}",
                f"{table.name}.{column.name}",
                column_text(table, column),
                splitter,
                {"table": table.name, "column": column.name, "type": column.type.lower()},
            )
    return specs


def item_chunks(items: Iterable[ItemInfo], splitter: Splitter) -> list[ChunkSpec]:
    specs: list[ChunkSpec] = []
    for item in items:
        key = f"item:{item.id}"
        if item.kind == "instruction":
            header = f"Instruction: {item.title}" if item.title else "Instruction"
            specs += _pieces("instruction", key, header, item.body, splitter, {})
        elif item.kind == "glossary":
            specs += _pieces(
                "glossary",
                key,
                f"Glossary: {item.title}",
                f"{item.title}: {item.body}",
                splitter,
                {"term": item.title},
            )
        elif item.kind == "clarification":
            specs += _pieces(
                "clarification",
                key,
                f"When to ask: {item.title}",
                f"When: {item.title}\nAsk: {item.body}",
                splitter,
                {"trigger": item.title, "ask": item.body},
            )
        elif item.kind == "example_sql":
            # What is embedded and matched is the question; the SQL travels in the metadata.
            text = f"{item.title}\n{item.note}".strip()
            meta = {"question": item.title, "sql": item.body, "trusted": item.trusted}
            specs += _pieces("example_sql", key, "Example question", text, splitter, meta)
    return specs


def document_chunks(
    doc_id: str, title: str, filename: str, pages: list[Page], splitter: Splitter
) -> list[ChunkSpec]:
    """A document's passages. Each is cut from one page (or slide) only, and says which, so an
    answer built on it can point at the page."""
    specs: list[ChunkSpec] = []
    offset = 0  # section numbers go on across pages: neighbours are only joined within a section
    for page in pages:
        chunks = splitter.split_markdown(page.markdown, title)
        for chunk in chunks:
            specs.append(
                ChunkSpec(
                    "document",
                    f"doc:{doc_id}",
                    len(specs),
                    chunk.header,
                    chunk.text,
                    {
                        "document": title,
                        "document_id": doc_id,
                        "filename": filename,
                        "page": page.number,
                        "ocr": page.ocr,
                        "section": offset + chunk.section,
                        "piece": chunk.piece,
                        "section_path": list(chunk.section_path),
                        "overlap_chars": chunk.overlap_chars,
                        "content": chunk.kind,
                    },
                )
            )
        offset += max((c.section for c in chunks), default=-1) + 1
    return specs


def _pieces(
    source_type: str,
    source_key: str,
    header: str,
    body: str,
    splitter: Splitter,
    meta: dict[str, Any],
) -> list[ChunkSpec]:
    return [
        ChunkSpec(source_type, source_key, index, chunk.header, chunk.text, meta)
        for index, chunk in enumerate(splitter.split_text(header, body))
    ]
