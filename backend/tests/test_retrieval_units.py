"""The pure parts of retrieval: keyword tokens, rank fusion, picking the final passages, joining."""

from app.rag.cards import (
    ColumnInfo,
    ItemInfo,
    JoinInfo,
    TableInfo,
    column_text,
    table_text,
)
from app.rag.retrieval import (
    Candidate,
    choose_final,
    join_neighbours,
    reciprocal_rank_fusion,
    tokens,
)


def test_keyword_tokens_drop_noise_trim_plurals_and_split_identifiers() -> None:
    assert tokens("What are the total Regions?") == ["total", "region"]
    assert tokens("customer_id") == ["customer_id", "customer", "id"]
    assert tokens("SKU-1043 sold 12 units") == ["sku", "1043", "sold", "12", "unit"]
    assert tokens("business class") == ["business", "class"]  # "ss" is not a plural


def test_fusion_rewards_ids_that_both_lists_agree_on() -> None:
    scores = reciprocal_rank_fusion([1, 2, 3], [3, 2, 9])

    ranked = sorted(scores, key=lambda i: -scores[i])
    assert ranked[:2] == [3, 2]  # both are in both lists; 3 is 1st in one, which counts a bit more
    assert set(ranked[2:]) == {1, 9}  # each is in one list only
    assert scores[1] == 1 / 61 and scores[9] == 1 / 63


def candidate(
    i: int,
    score: float,
    *,
    source_type: str = "column",
    key: str = "",
    position: int = 0,
    section: int = 0,
    overlap: int = 0,
    text: str = "",
) -> Candidate:
    return Candidate(
        i,
        source_type,
        key or f"column:{i}",
        position,
        f"header {i}",
        text or f"text {i}",
        {"section": section, "overlap_chars": overlap},
        rerank_score=score,
    )


def test_final_picks_those_above_the_threshold_but_never_fewer_than_five() -> None:
    ranked = [candidate(i, 10.0 - i) for i in range(30)]  # scores 10, 9, ... -19

    assert [c.id for c in choose_final(ranked, threshold=0.0)] == list(range(10))  # capped at 10
    assert [c.id for c in choose_final(ranked, threshold=3.5)] == list(range(7))  # 10 down to 4
    assert len(choose_final(ranked, threshold=100.0)) == 5  # nothing clears it: best five
    assert len(choose_final(ranked[:3], threshold=100.0)) == 3  # only three exist


def test_neighbouring_pieces_of_a_section_are_joined_without_repeating_the_overlap() -> None:
    first = candidate(
        1, 3.0, source_type="document", key="doc:a", position=4, text="alpha beta gamma"
    )
    second = candidate(
        2,
        5.0,
        source_type="document",
        key="doc:a",
        position=5,
        overlap=11,
        text="beta gamma\ndelta",
    )
    other_section = candidate(3, 1.0, source_type="document", key="doc:a", position=6, section=1)
    for rank, c in enumerate([second, first, other_section], start=1):
        c.final_rank = rank
    lone = candidate(4, 2.0)
    lone.final_rank = 4

    passages = join_neighbours([second, first, other_section, lone])

    assert [p.chunk_ids for p in passages] == [(1, 2), (3,), (4,)]
    assert passages[0].text == "alpha beta gamma\ndelta"  # "beta gamma\n" is not said twice
    assert passages[0].score == 5.0


def test_pieces_that_are_not_adjacent_stay_separate() -> None:
    a = candidate(1, 3.0, source_type="document", key="doc:a", position=1)
    b = candidate(2, 2.0, source_type="document", key="doc:a", position=3)
    a.final_rank, b.final_rank = 1, 2

    assert [p.chunk_ids for p in join_neighbours([a, b])] == [(1,), (2,)]


def test_a_table_card_lists_visible_columns_and_joins_and_hides_the_rest() -> None:
    table = TableInfo(
        "t1",
        "sales",
        "One row per order",
        1200,
        (
            ColumnInfo("c1", "order_id", "BIGINT"),
            ColumnInfo("c2", "internal_note", "VARCHAR", hidden=True),
        ),
    )
    joins = [JoinInfo("sales", "customer_id", "customers", "id", "many_to_one")]

    text = table_text(table, joins)

    assert "One row per order" in text and "1,200 rows" in text
    assert "order_id (bigint)" in text and "internal_note" not in text
    assert "sales.customer_id = customers.id (many to one)" in text


def test_a_column_card_shares_values_only_when_allowed() -> None:
    stats = {
        "top_values": [{"value": "West", "count": 150}],
        "min": "East",
        "max": "West",
        "null_pct": 4.0,
    }
    table = TableInfo("t1", "sales", "", 10, ())
    shown = ColumnInfo("c1", "region", "VARCHAR", "Sales region", ("zone",), stats=stats)
    private = ColumnInfo("c1", "region", "VARCHAR", "Sales region", share_values=False, stats=stats)

    assert "Common values: West (150)." in column_text(table, shown)
    assert "Also called: zone." in column_text(table, shown)
    assert "West" not in column_text(table, private)
    assert "4.0% of values are empty" in column_text(table, private)


def test_items_know_what_they_are() -> None:
    assert ItemInfo("1", "instruction", "", "Round to two decimals").kind == "instruction"
