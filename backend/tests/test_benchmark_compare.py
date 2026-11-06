"""Comparing the assistant's result with the reference result (no database needed)."""

from app.chat.benchmark_compare import compare_results
from app.engine.duckdb_engine import Column, QueryResult


def result(rows: list[list], names: tuple[str, ...] = ("a", "b"), truncated: bool = False):
    width = len(rows[0]) if rows else len(names)
    columns = [Column(names[i] if i < len(names) else f"c{i}", "VARCHAR") for i in range(width)]
    return QueryResult(columns=columns, rows=rows, truncated=truncated, elapsed_ms=1)


def test_the_same_rows_are_correct_whatever_the_column_names_are() -> None:
    reference = result([["Mina", 90], ["Asha", 30]], ("customer", "revenue"))
    answer = result([["Mina", 90], ["Asha", 30]], ("name", "total"))

    assert compare_results(reference, answer, ordered=False).correct


def test_the_order_of_rows_does_not_matter_unless_the_reference_sorts() -> None:
    reference = result([["Mina", 90], ["Asha", 30]])
    shuffled = result([["Asha", 30], ["Mina", 90]])

    assert compare_results(reference, shuffled, ordered=False).correct
    verdict = compare_results(reference, shuffled, ordered=True)
    assert not verdict.correct and "different order" in verdict.reason


def test_columns_in_another_order_are_still_the_same_answer() -> None:
    reference = result([["Mina", 90], ["Asha", 30]])
    swapped = result([[90, "Mina"], [30, "Asha"]])

    assert compare_results(reference, swapped, ordered=False).correct
    assert compare_results(reference, swapped, ordered=True).correct


def test_a_swap_does_not_hide_a_wrong_pairing_of_values() -> None:
    reference = result([["Mina", 90], ["Asha", 30]])
    mismatched = result([[30, "Mina"], [90, "Asha"]])  # right values, paired wrongly

    assert not compare_results(reference, mismatched, ordered=False).correct


def test_numbers_agree_to_about_nine_digits_and_ints_equal_floats() -> None:
    reference = result([[90, 0.3]])

    assert compare_results(reference, result([[90.0, 0.1 + 0.2]]), ordered=False).correct
    assert not compare_results(reference, result([[90, 0.31]]), ordered=False).correct
    assert not compare_results(result([[1000000]]), result([[1000001]]), ordered=False).correct


def test_surrounding_spaces_are_ignored_but_case_is_not() -> None:
    reference = result([["Mina"]])

    assert compare_results(reference, result([[" Mina "]]), ordered=False).correct
    assert not compare_results(reference, result([["mina"]]), ordered=False).correct


def test_nulls_and_booleans_are_compared_as_themselves() -> None:
    reference = result([[None, True]])

    assert compare_results(reference, result([[None, True]]), ordered=False).correct
    assert not compare_results(reference, result([["", True]]), ordered=False).correct
    assert not compare_results(reference, result([[None, 1]]), ordered=False).correct


def test_a_wrong_number_of_columns_or_rows_is_reported_with_the_counts() -> None:
    reference = result([["Mina", 90], ["Asha", 30]])

    wide = compare_results(reference, result([["Mina", 90, 1], ["Asha", 30, 1]]), ordered=False)
    short = compare_results(reference, result([["Mina", 90]]), ordered=False)

    assert not wide.correct and "3 columns" in wide.reason and "has 2" in wide.reason
    assert not short.correct and "1 row" in short.reason and "2 rows" in short.reason


def test_different_values_say_how_many_rows_differ_without_quoting_any_value() -> None:
    reference = result([["Mina", 90], ["Asha", 30], ["Ravi", 30]])
    answer = result([["Mina", 90], ["Asha", 31], ["Ravi", 30]])

    verdict = compare_results(reference, answer, ordered=False)

    assert not verdict.correct and "1 of the 3 reference rows" in verdict.reason
    for value in ("Mina", "Asha", "90", "31"):
        assert value not in verdict.reason


def test_two_empty_results_agree_and_an_empty_one_does_not_match_a_full_one() -> None:
    empty = QueryResult(columns=[Column("a", "INTEGER")], rows=[], truncated=False, elapsed_ms=1)

    assert compare_results(empty, empty, ordered=False).correct
    assert not compare_results(empty, result([[1]], ("a",)), ordered=False).correct


def test_a_result_that_was_cut_short_cannot_be_judged() -> None:
    cut = result([[1]], ("a",), truncated=True)

    verdict = compare_results(cut, result([[1]], ("a",)), ordered=False)

    assert not verdict.correct and "too many rows" in verdict.reason


def test_json_and_other_values_compare_by_content() -> None:
    reference = result([[{"b": 1, "a": 2}]], ("a",))

    assert compare_results(reference, result([[{"a": 2, "b": 1}]], ("a",)), ordered=False).correct
