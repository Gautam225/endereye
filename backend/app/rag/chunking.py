"""Splitting Markdown (and plain text) into chunks that fit the embedding model.

The rules are the project's, from docs/ROADMAP.md section 4.2:

- Split by section first (on headings). A section that fits stays whole.
- A section that is too long is split recursively: paragraphs, lines, sentences, words.
- A code block is not split, a long table is split by rows with its header row repeated in
  every piece. (Only a block that cannot fit in the model's limit even alone is cut further.)
- Neighbouring pieces of one section overlap by a few tokens; separate sections never do.
- Every chunk is embedded with a header such as `Sales Policy > Discounts > Regional rules`.
- Sizes are measured with the embedding model's own tokenizer, and header + text always fit
  inside its 512-token limit, so nothing is ever silently cut off.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.rag.constants import MAX_EMBED_TOKENS, TooLongError

Kind = Literal["prose", "table", "code"]

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
MAX_HEADER_CHARS = 200
SEPARATORS = ("\n\n", "\n", "sentence", " ")


@dataclass(frozen=True, slots=True)
class Chunk:
    header: str
    text: str
    # How many characters at the start of `text` repeat the end of the previous piece.
    overlap_chars: int = 0
    section: int = 0  # section number within the document
    piece: int = 0  # piece number within the section
    section_path: tuple[str, ...] = ()
    kind: Kind = "prose"

    @property
    def embed_text(self) -> str:
        return f"{self.header}\n{self.text}"


@dataclass(slots=True)
class _Block:
    kind: Kind
    text: str
    sealed: bool = False  # produced by splitting a big block: always its own piece


Counter = Callable[[str], int]
Tail = Callable[[str, int], str]


class Splitter:
    def __init__(
        self,
        count: Counter,
        tail: Tail,
        *,
        text_tokens: int = 450,
        overlap_tokens: int = 40,
        max_tokens: int = MAX_EMBED_TOKENS,
    ) -> None:
        self._count, self._tail = count, tail
        self.text_tokens, self.overlap_tokens, self.max_tokens = (
            text_tokens,
            overlap_tokens,
            max_tokens,
        )

    # ── Public ───────────────────────────────────────────────────────────────

    def split_markdown(self, markdown: str, title: str) -> list[Chunk]:
        """A whole document, section by section."""
        chunks: list[Chunk] = []
        for number, (path, lines) in enumerate(_sections(markdown)):
            blocks = _blocks(lines)
            if blocks:
                chunks += self._section(_header(title, path), blocks, number, path)
        return chunks

    def split_text(self, header: str, body: str) -> list[Chunk]:
        """One item's text (an instruction, a glossary entry...) under a fixed header."""
        blocks = _blocks(body.splitlines())
        return self._section(_header(header, ()), blocks, 0, ()) if blocks else []

    # ── One section ──────────────────────────────────────────────────────────

    def _tokens(self, text: str) -> int:
        """Tokens a piece of text adds to a chunk (the two special tokens are counted once)."""
        return max(self._count(text) - 2, 0)

    def _section(
        self, header: str, blocks: list[_Block], section: int, path: tuple[str, ...]
    ) -> list[Chunk]:
        header_cost = self._count(header + "\n")
        room = self.max_tokens - header_cost
        if room < 32:
            raise TooLongError(f"The header {header!r} leaves no room for text")
        for shrink in (1.0, 0.85, 0.7, 0.5, 0.3):
            budget = max(int(min(self.text_tokens, room) * shrink), 16)
            chunks = self._pieces(header, blocks, budget, section, path)
            if all(self._count(c.embed_text) <= self.max_tokens for c in chunks):
                return chunks
        raise TooLongError(f"Could not fit a chunk under {header!r} in {self.max_tokens} tokens")

    def _pieces(
        self,
        header: str,
        blocks: list[_Block],
        budget: int,
        section: int,
        path: tuple[str, ...],
    ) -> list[Chunk]:
        whole = "\n\n".join(b.text for b in blocks)
        if self._tokens(whole) <= budget:
            kinds = {b.kind for b in blocks}
            kind: Kind = "prose" if kinds == {"prose"} else blocks[0].kind
            return [Chunk(header, whole, 0, section, 0, path, kind)]

        # Pieces after the first start with an overlap, so that room is kept free.
        room = budget - (self.overlap_tokens if self.overlap_tokens else 0)
        room = max(room, 16)
        groups: list[list[_Block]] = []
        current: list[_Block] = []
        used = 0
        for block in self._fit(blocks, room):
            cost = self._tokens(block.text)
            if block.sealed or used + cost > room:
                if current:
                    groups.append(current)
                current, used = [], 0
            current.append(block)
            used += cost
            if block.sealed:
                groups.append(current)
                current, used = [], 0
        if current:
            groups.append(current)

        chunks: list[Chunk] = []
        previous: Chunk | None = None
        for index, group in enumerate(groups):
            text = "\n\n".join(b.text for b in group)
            overlap = 0
            if (
                previous is not None
                and self.overlap_tokens
                and previous.kind == "prose"
                and group[0].kind == "prose"
            ):
                lead = self._tail(previous.text[previous.overlap_chars :], self.overlap_tokens)
                if lead.strip():
                    text, overlap = lead.rstrip() + "\n" + text, len(lead.rstrip()) + 1
            kinds = {b.kind for b in group}
            kind = "prose" if kinds == {"prose"} else group[0].kind
            previous = Chunk(header, text, overlap, section, index, path, kind)
            chunks.append(previous)
        return chunks

    # ── Splitting one block that is too big ──────────────────────────────────

    def _fit(self, blocks: list[_Block], room: int) -> list[_Block]:
        fitted: list[_Block] = []
        for block in blocks:
            if self._tokens(block.text) <= room:
                fitted.append(block)
            elif block.kind == "table":
                fitted += self._split_table(block.text, room)
            elif block.kind == "code":
                fitted += self._split_code(block.text, room)
            else:
                fitted += [_Block("prose", t, True) for t in self._split_prose(block.text, room)]
        return fitted

    def _split_table(self, text: str, room: int) -> list[_Block]:
        lines = text.splitlines()
        head = lines[:2] if len(lines) > 1 and TABLE_SEPARATOR.match(lines[1]) else lines[:1]
        rows = lines[len(head) :]
        head_cost = self._tokens("\n".join(head))
        pieces: list[_Block] = []
        current: list[str] = []
        used = head_cost
        for row in rows:
            cost = self._tokens(row)
            if head_cost + cost > room:  # one row alone is too long: treat it as prose
                if current:
                    pieces.append(_Block("table", "\n".join([*head, *current]), True))
                    current, used = [], head_cost
                pieces += [_Block("prose", t, True) for t in self._split_prose(row, room)]
                continue
            if used + cost > room and current:
                pieces.append(_Block("table", "\n".join([*head, *current]), True))
                current, used = [], head_cost
            current.append(row)
            used += cost
        if current:
            pieces.append(_Block("table", "\n".join([*head, *current]), True))
        return pieces

    def _split_code(self, text: str, room: int) -> list[_Block]:
        """A code block is kept whole when it fits in the model's limit; this is the last resort."""
        lines = text.splitlines()
        opening, closing = lines[0], lines[-1] if len(lines) > 1 and FENCE.match(lines[-1]) else ""
        body = lines[1:-1] if closing else lines[1:]
        wrap = self._tokens(opening) + self._tokens(closing)
        pieces: list[_Block] = []
        current: list[str] = []
        used = wrap
        for line in body:
            cost = self._tokens(line)
            if used + cost > room and current:
                pieces.append(
                    _Block("code", "\n".join([opening, *current, closing or "```"]), True)
                )
                current, used = [], wrap
            if wrap + cost > room:  # a single line that is too long
                for part in self._hard_split(line, max(room - wrap, 8)):
                    pieces.append(
                        _Block("code", "\n".join([opening, part, closing or "```"]), True)
                    )
                continue
            current.append(line)
            used += cost
        if current:
            pieces.append(_Block("code", "\n".join([opening, *current, closing or "```"]), True))
        return pieces

    def _split_prose(self, text: str, room: int, level: int = 0) -> list[str]:
        """Recursively: paragraphs, then lines, then sentences, then words."""
        if self._tokens(text) <= room:
            return [text]
        if level >= len(SEPARATORS):
            return self._hard_split(text, room)
        separator = SEPARATORS[level]
        parts = SENTENCE_END.split(text) if separator == "sentence" else text.split(separator)
        joiner = " " if separator == "sentence" else separator
        pieces: list[str] = []
        current: list[str] = []
        used = 0
        for part in parts:
            if not part.strip():
                continue
            cost = self._tokens(part)
            if cost > room:
                if current:
                    pieces.append(joiner.join(current))
                    current, used = [], 0
                pieces += self._split_prose(part, room, level + 1)
                continue
            if used + cost > room and current:
                pieces.append(joiner.join(current))
                current, used = [], 0
            current.append(part)
            used += cost
        if current:
            pieces.append(joiner.join(current))
        return pieces

    def _hard_split(self, text: str, room: int) -> list[str]:
        """Last resort for something with no break points (a very long unbroken string)."""
        pieces: list[str] = []
        while text:
            size = len(text)
            while size > 1 and self._tokens(text[:size]) > room:
                size = max(size // 2, 1)
            pieces.append(text[:size])
            text = text[size:]
        return pieces


# ── Parsing Markdown into sections and blocks ────────────────────────────────


def _header(title: str, path: tuple[str, ...]) -> str:
    parts: list[str] = []
    for part in (title, *path):
        part = " ".join(part.split())
        if part and (not parts or parts[-1].lower() != part.lower()):
            parts.append(part)
    return " › ".join(parts)[:MAX_HEADER_CHARS]  # noqa: RUF001


def _sections(markdown: str) -> list[tuple[tuple[str, ...], list[str]]]:
    """(heading path, body lines) for each section; text before any heading comes first."""
    sections: list[tuple[tuple[str, ...], list[str]]] = []
    stack: list[tuple[int, str]] = []
    path: tuple[str, ...] = ()
    lines: list[str] = []
    in_code = False
    for line in markdown.splitlines():
        if FENCE.match(line):
            in_code = not in_code
        match = None if in_code else HEADING.match(line)
        if match:
            sections.append((path, lines))
            level, text = len(match.group(1)), match.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            path = tuple(t for _, t in stack)
            lines = []
        else:
            lines.append(line)
    sections.append((path, lines))
    return [(p, ls) for p, ls in sections if any(line.strip() for line in ls)]


def _blocks(lines: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            text = "\n".join(paragraph).strip()
            if text:
                blocks.append(_Block("prose", text))
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if FENCE.match(line):
            flush()
            end = index + 1
            while end < len(lines) and not FENCE.match(lines[end]):
                end += 1
            blocks.append(_Block("code", "\n".join(lines[index : end + 1])))
            index = end + 1
        elif line.lstrip().startswith("|"):
            flush()
            end = index
            while end < len(lines) and lines[end].lstrip().startswith("|"):
                end += 1
            blocks.append(_Block("table", "\n".join(lines[index:end])))
            index = end
        elif not line.strip():
            flush()
            index += 1
        else:
            paragraph.append(line)
            index += 1
    flush()
    return blocks
