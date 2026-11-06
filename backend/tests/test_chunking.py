"""Chunking with the real embedding tokenizer: sizes, overlap, tables, code, and the 512 limit."""

import random
from itertools import pairwise
from pathlib import Path

import pytest

from app.rag.chunking import Chunk, Splitter
from app.rag.models import MAX_EMBED_TOKENS, Embedder, ModelConfig, TooLongError, get_embedder

MODELS = Path(__file__).resolve().parents[2] / "data" / "models"


@pytest.fixture(scope="session")
def embedder() -> Embedder:
    return get_embedder(ModelConfig("BAAI/bge-small-en-v1.5", "unused", MODELS))


@pytest.fixture
def splitter(embedder: Embedder) -> Splitter:
    return Splitter(embedder.count, embedder.tail, text_tokens=450, overlap_tokens=40)


def tokens(embedder: Embedder, chunks: list[Chunk]) -> list[int]:
    return [embedder.count(c.embed_text) for c in chunks]


def sentence(i: int) -> str:
    return f"Rule {i} says that orders from region {i % 7} are reviewed by team {i % 5} each week."


def prose(sentences: int) -> str:
    return " ".join(sentence(i) for i in range(sentences))


def test_a_short_section_stays_whole_under_its_path(splitter: Splitter) -> None:
    markdown = "# Sales Policy 2025\n\nIntro text.\n\n## Discounts\n\nFive percent for bronze."

    chunks = splitter.split_markdown(markdown, "Sales Policy 2025")

    assert [(c.header, c.text) for c in chunks] == [
        ("Sales Policy 2025", "Intro text."),
        ("Sales Policy 2025 › Discounts", "Five percent for bronze."),  # noqa: RUF001
    ]


def test_headings_nest_and_pop_by_level(splitter: Splitter) -> None:
    markdown = "# A\n## B\ntext b\n### C\ntext c\n## D\ntext d\n# E\ntext e"

    paths = [c.section_path for c in splitter.split_markdown(markdown, "Doc")]

    assert paths == [("A", "B"), ("A", "B", "C"), ("A", "D"), ("E",)]


def test_long_sections_are_split_with_overlap_and_always_fit(
    splitter: Splitter, embedder: Embedder
) -> None:
    chunks = splitter.split_markdown("# Rules\n\n" + prose(300), "Handbook")

    assert len(chunks) > 3
    assert max(tokens(embedder, chunks)) <= MAX_EMBED_TOKENS
    assert [c.piece for c in chunks] == list(range(len(chunks)))
    for before, after in pairwise(chunks):
        assert after.overlap_chars > 0
        repeated = after.text[: after.overlap_chars].strip()
        assert repeated and repeated in before.text  # the overlap really is the previous end
        assert embedder.count(repeated) <= 45


def test_separate_sections_never_overlap(splitter: Splitter) -> None:
    markdown = f"# One\n\n{prose(120)}\n\n# Two\n\n{prose(120)}"

    chunks = splitter.split_markdown(markdown, "Doc")

    firsts = [c for c in chunks if c.piece == 0]
    assert len(firsts) == 2 and all(c.overlap_chars == 0 for c in firsts)
    assert {c.section for c in chunks} == {0, 1}


def test_a_long_table_is_split_by_rows_and_repeats_its_header(
    splitter: Splitter, embedder: Embedder
) -> None:
    rows = [
        f"| SKU-{i:04d} | Product number {i} | {i * 3} | {'yes' if i % 2 else 'no'} |"
        for i in range(200)
    ]
    table = "\n".join(["| SKU | Name | Price | Stocked |", "| --- | --- | --- | --- |", *rows])

    chunks = splitter.split_markdown(f"# Catalogue\n\n{table}", "Doc")

    assert len(chunks) > 1 and max(tokens(embedder, chunks)) <= MAX_EMBED_TOKENS
    for chunk in chunks:
        assert chunk.kind == "table"
        assert chunk.text.splitlines()[:2] == [
            "| SKU | Name | Price | Stocked |",
            "| --- | --- | --- | --- |",
        ]
        assert chunk.overlap_chars == 0
    kept = [line for c in chunks for line in c.text.splitlines()[2:]]
    assert kept == rows  # every row exactly once, in order


def test_a_code_block_that_fits_is_never_split(splitter: Splitter) -> None:
    code = "```sql\n" + "\n".join(f"SELECT {i} AS col_{i};" for i in range(25)) + "\n```"
    markdown = f"# Queries\n\n{prose(40)}\n\n{code}\n\n{prose(40)}"

    chunks = splitter.split_markdown(markdown, "Doc")

    holders = [c for c in chunks if "SELECT 0 AS col_0" in c.text]
    assert len(holders) == 1 and code in holders[0].text


def test_a_code_block_too_big_for_the_model_is_cut_on_line_boundaries(
    splitter: Splitter, embedder: Embedder
) -> None:
    code = (
        "```python\n"
        + "\n".join(f"value_{i} = compute({i}, 'label {i}')" for i in range(400))
        + "\n```"
    )

    chunks = splitter.split_markdown(f"# Code\n\n{code}", "Doc")

    assert len(chunks) > 1 and max(tokens(embedder, chunks)) <= MAX_EMBED_TOKENS
    assert all(c.text.startswith("```python") and c.text.endswith("```") for c in chunks)
    lines = [line for c in chunks for line in c.text.splitlines() if line.startswith("value_")]
    assert lines == [f"value_{i} = compute({i}, 'label {i}')" for i in range(400)]


@pytest.mark.parametrize(
    "body",
    ids=["unbroken", "no-punctuation", "tiny-lines", "tiny-paragraphs", "unicode", "urls"],
    argvalues=[
        "x" * 6000,  # one unbroken string
        "word " * 3000,  # no punctuation, no paragraphs
        "\n".join(f"line {i}" for i in range(2000)),  # thousands of tiny lines
        "\n\n".join(f"para {i}." for i in range(1500)),  # thousands of tiny paragraphs
        "Ünïcödé テキスト 文章 " * 800,  # not English
        " ".join(f"https://example.com/path/{i}/segment?x={i}" for i in range(300)),
    ],
)
def test_nothing_ever_exceeds_the_embedders_limit(
    splitter: Splitter, embedder: Embedder, body: str
) -> None:
    chunks = splitter.split_markdown(f"# Title\n\n{body}", "A rather long document title " * 3)

    assert chunks and max(tokens(embedder, chunks)) <= MAX_EMBED_TOKENS
    embedder.embed([c.embed_text for c in chunks[:3]])  # and the embedder accepts them


def test_no_text_is_lost_when_splitting(splitter: Splitter) -> None:
    random.seed(7)
    words = [f"w{random.randrange(10_000)}" for _ in range(4000)]
    markdown = "# Big\n\n" + " ".join(words)

    chunks = splitter.split_markdown(markdown, "Doc")

    seen = {w for c in chunks for w in c.text.split()}
    assert set(words) <= seen


def test_items_are_split_under_their_own_header(splitter: Splitter, embedder: Embedder) -> None:
    chunks = splitter.split_text("Instruction: fiscal year", prose(200))

    assert len(chunks) > 1 and {c.header for c in chunks} == {"Instruction: fiscal year"}
    assert max(tokens(embedder, chunks)) <= MAX_EMBED_TOKENS
    assert splitter.split_text("Empty", "   ") == []


def test_the_embedder_refuses_text_it_would_cut_off(embedder: Embedder) -> None:
    with pytest.raises(TooLongError):
        embedder.embed(["word " * 600])
    assert len(embedder.embed(["short text"])[0]) == 384


def test_tail_returns_the_last_words(embedder: Embedder) -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"

    tail = embedder.tail(text, 3)

    assert text.endswith(tail) and 1 <= len(tail.split()) <= 4
    assert embedder.tail("short", 40) == "short"
