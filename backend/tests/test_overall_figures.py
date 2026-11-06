"""A question that asks for several figures: all of them come back, each is charted on its own,
the overall figures come from the database, and a figure that is missing is never a silent gap."""

# The fixtures imported from test_spaces are used by name, which ruff reads as a redefinition.
# ruff: noqa: F811

import csv
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, ask, conversation, events, final, small_space, sql_plan, use
from test_knowledge import sales_csv
from test_spaces import admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.chat.prompts import ShownFigure

pytestmark = pytest.mark.db

THREE = (
    "SELECT region, avg(amount) AS average_amount, count(*) AS orders, "
    "sum(amount) AS total_amount FROM sales GROUP BY region ORDER BY average_amount DESC"
)
SHOWS = [
    ShownFigure(ask="average order value", column="average_amount"),
    ShownFigure(ask="number of orders", column="orders"),
    ShownFigure(ask="total sales", column="total_amount"),
]


def overall_from_the_file() -> dict[str, float]:
    """What the whole file says, worked out here without the app."""
    amounts = [float(r["amount"]) for r in csv.DictReader(io.StringIO(sales_csv().decode()))]
    return {
        "average_amount": sum(amounts) / len(amounts),
        "orders": float(len(amounts)),
        "total_amount": sum(amounts),
    }


def asked(
    api: TestClient,
    plan_sql: str,
    space: tuple[Any, str] | None = None,
    **extra: object,
) -> tuple[list, dict, FakeLLM]:
    """Ask in a new chat of the sales space (made here unless one is passed in)."""
    boss, space_id = space or (lambda b: (b, small_space(b)))(admin(api))
    fake = FakeLLM(chat_sql=[sql_plan(plan_sql, **extra)])
    use(api, fake)
    found = events(ask(boss, space_id, conversation(boss, space_id), "Compare the regions"))
    return found, final(found), fake


# ── Several figures: one chart each, and the overall figures from the database ──


def test_a_comparison_of_three_figures_has_a_chart_each_and_the_overall_figures(
    api: TestClient,
) -> None:
    found, message, _ = asked(api, THREE, shows=SHOWS)

    chart = message["chart"]
    assert [panel["y"] for panel in chart["panels"]] == [
        ["average_amount"],
        ["orders"],
        ["total_amount"],
    ]
    assert [t["name"] for t in chart["totals"]] == ["average_amount", "orders", "total_amount"]
    assert [t["kind"] for t in chart["totals"]] == ["avg", "count", "sum"]
    expected = overall_from_the_file()
    for tile in chart["totals"]:
        assert tile["value"] == pytest.approx(expected[tile["name"]])
    notes = [d["text"] for n, d in found if n == "thought"]
    assert any("overall figures" in note for note in notes)
    assert message["attempts"] == 1 and "overall" in message["timings"]


def test_the_overall_figures_are_given_to_the_assistant_and_not_worked_out_by_it(
    api: TestClient,
) -> None:
    _, _, fake = asked(api, THREE, shows=SHOWS)

    (prompt,) = fake.prompts("chat_explain")
    assert "Overall figures over all rows (computed by the database)" in prompt
    assert "never add up or average the rows yourself" in prompt
    (sql_prompt,) = fake.prompts("chat_sql")
    assert "`shows`" in sql_prompt and "Do not add a total row" in sql_prompt


def test_one_measure_is_its_own_answer_and_asks_the_database_nothing_more(
    api: TestClient,
) -> None:
    _, message, _ = asked(api, "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1")

    assert "totals" not in message["chart"] and "panels" not in message["chart"]


def test_no_overall_figures_when_a_having_picked_some_of_the_groups(api: TestClient) -> None:
    having = THREE.replace("GROUP BY region", "GROUP BY region HAVING count(*) > 1")

    _, message, _ = asked(api, having)

    assert len(message["chart"]["panels"]) == 3  # still one chart each
    assert "totals" not in message["chart"]  # but a total over only some groups would mislead


def test_a_limit_that_cut_groups_off_means_no_overall_figures_but_one_that_did_not_is_fine(
    api: TestClient,
) -> None:
    boss = admin(api)
    space = (boss, small_space(boss))
    _, cut, _ = asked(api, THREE + " LIMIT 2", space)
    _, whole, _ = asked(api, THREE + " LIMIT 100", space)

    assert cut["row_count"] == 2 and "totals" not in cut["chart"]
    assert whole["row_count"] == 4 and len(whole["chart"]["totals"]) == 3


def test_the_overall_figures_survive_a_reload(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    use(api, FakeLLM(chat_sql=[sql_plan(THREE)]))
    cid = conversation(boss, space_id)

    message = final(events(ask(boss, space_id, cid, "Compare the regions")))

    saved = boss.get(f"/spaces/{space_id}/conversations/{cid}").json()["messages"][0]
    assert saved["chart"]["totals"] == message["chart"]["totals"]


# ── A figure that was asked for must be in the result ────────────────────────


def test_a_missing_figure_is_asked_for_again_once(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    without_total = (
        "SELECT region, avg(amount) AS average_amount, count(*) AS orders FROM sales "
        "GROUP BY region ORDER BY average_amount DESC"
    )
    fake = FakeLLM(
        chat_sql=[sql_plan(without_total, shows=SHOWS)],
        chat_repair=[sql_plan(THREE, shows=SHOWS)],
    )
    use(api, fake)

    found = events(ask(boss, space_id, conversation(boss, space_id), "Compare the regions"))

    message = final(found)
    assert message["attempts"] == 2 and message["sql"] == THREE
    assert [c["name"] for c in message["columns"]] == [
        "region",
        "average_amount",
        "orders",
        "total_amount",
    ]
    (repair,) = fake.prompts("chat_repair")
    assert "The question asks to show total sales (column total_amount)" in repair
    assert "It returned: region, average_amount, orders" in repair
    notes = [d["text"] for n, d in found if n == "thought" and d["kind"] == "note"]
    assert any("left out total sales" in note for note in notes)
    assert "does not include" not in message["answer"]


def test_a_figure_still_missing_on_the_last_try_is_said_in_the_answer(api: TestClient) -> None:
    boss = admin(api)
    space_id = small_space(boss)
    without_total = (
        "SELECT region, avg(amount) AS average_amount, count(*) AS orders FROM sales "
        "GROUP BY region ORDER BY average_amount DESC"
    )
    stubborn = sql_plan(without_total, shows=SHOWS)
    fake = FakeLLM(chat_sql=[stubborn], chat_repair=[stubborn])  # the last item repeats
    use(api, fake)

    found = events(ask(boss, space_id, conversation(boss, space_id), "Compare the regions"))

    message = final(found)
    assert message["status"] == "ok" and message["attempts"] == 3  # shown, not failed
    assert "> The result does not include total sales" in message["answer"]
    assert len(message["chart"]["panels"]) == 2  # what it has is still charted
    notes = [d["text"] for n, d in found if n == "thought" and d["kind"] == "note"]
    assert any("does not include total sales" in note for note in notes)


def test_a_column_the_database_returns_in_another_case_is_not_missing(api: TestClient) -> None:
    shouting = [ShownFigure(ask="total sales", column="TOTAL_AMOUNT")]

    _, message, fake = asked(api, THREE, shows=shouting)

    assert message["attempts"] == 1 and "chat_repair" not in fake.purposes()


def test_a_question_that_names_no_figures_is_not_checked(api: TestClient) -> None:
    _, message, fake = asked(api, THREE)  # `shows` left empty

    assert message["attempts"] == 1 and "chat_repair" not in fake.purposes()
