"""Benchmarks: questions with a reference SQL, and runs that score the assistant on the real
results (needs the test database). The assistant is scripted, so each outcome is exercised on
purpose; the data, the SQL guard and the comparison are all real."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat import FakeLLM, sql_plan, use
from test_knowledge import customers_csv, sales_csv
from test_spaces import Person, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.chat.prompts import SqlPlan
from app.llm.errors import LLMUnavailableError
from app.services import benchmarks as service

pytestmark = pytest.mark.db

REVENUE = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
REVENUE_OTHER_WAY = "SELECT sum(amount) AS total, region AS area FROM sales GROUP BY region"
WRONG = "SELECT region, avg(amount) AS revenue FROM sales GROUP BY 1"
ORDERS = "SELECT count(*) AS n FROM sales"


def sales_space(boss: Person) -> str:
    space_id = new_space(boss)
    assert boss.upload(space_id, "sales.csv", sales_csv()).status_code == 201
    return space_id


def add_item(boss: Person, space_id: str, question: str, sql: str, **extra: Any) -> Any:
    return boss.post(
        f"/spaces/{space_id}/benchmarks",
        json={"question": question, "expected_sql": sql, **extra},
    )


def wait_for(boss: Person, space_id: str, run_id: str, seconds: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = boss.get(f"/spaces/{space_id}/benchmarks/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("the run did not finish")


def run_all(boss: Person, space_id: str, **body: Any) -> dict[str, Any]:
    started = boss.post(f"/spaces/{space_id}/benchmarks/runs", json=body)
    assert started.status_code == 202, started.text
    return wait_for(boss, space_id, started.json()["id"])


# ── The questions ────────────────────────────────────────────────────────────


def test_a_benchmark_question_is_saved_only_when_its_reference_sql_really_runs(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = sales_space(boss)

    saved = add_item(boss, space_id, "Revenue by region?", REVENUE)
    unknown_column = add_item(boss, space_id, "Revenue by area?", "SELECT area FROM sales")
    write = add_item(boss, space_id, "Delete them?", "DELETE FROM sales")
    other_table = add_item(boss, space_id, "Staff?", "SELECT * FROM staff")

    assert saved.status_code == 201 and saved.json()["last_outcome"] is None
    for refused in (unknown_column, write, other_table):
        assert refused.status_code == 400, refused.text
    assert [i["question"] for i in boss.get(f"/spaces/{space_id}/benchmarks").json()] == [
        "Revenue by region?"
    ]


def test_questions_can_be_edited_and_deleted_and_are_limited(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    item = add_item(boss, space_id, "Revenue by region?", REVENUE).json()

    renamed = boss.patch(
        f"/spaces/{space_id}/benchmarks/{item['id']}", json={"question": "Sales per region?"}
    )
    broken = boss.patch(
        f"/spaces/{space_id}/benchmarks/{item['id']}", json={"expected_sql": "SELECT nope"}
    )
    assert renamed.json()["question"] == "Sales per region?"
    assert broken.status_code == 400
    assert boss.get(f"/spaces/{space_id}/benchmarks").json()[0]["expected_sql"] == REVENUE

    monkeypatch.setattr(service, "MAX_COMPARED_ROWS", 3)
    big = add_item(boss, space_id, "Every order?", "SELECT order_id FROM sales")
    assert big.status_code == 400 and "more than 3 rows" in big.text

    assert boss.delete(f"/spaces/{space_id}/benchmarks/{item['id']}").status_code == 204
    assert boss.get(f"/spaces/{space_id}/benchmarks").json() == []
    assert boss.delete(f"/spaces/{space_id}/benchmarks/{item['id']}").status_code == 404


def test_the_number_of_questions_per_space_is_limited(
    settings: Any, clean_db: None, data_dir: Any
) -> None:
    custom = settings.model_copy(update={"data_dir": data_dir, "benchmark_max_items": 1})
    from app.main import create_app

    with TestClient(create_app(custom)) as client:
        boss = admin(client)
        space_id = sales_space(boss)
        assert add_item(boss, space_id, "Revenue by region?", REVENUE).status_code == 201
        second = add_item(boss, space_id, "How many orders?", ORDERS)
        assert (second.status_code, code(second)) == (400, "too_many_benchmarks")


def test_only_editors_of_the_space_can_see_or_use_benchmarks(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    item = add_item(boss, space_id, "Revenue by region?", REVENUE).json()
    viewer = person(api, boss, "vi@example.com", "viewer")
    stranger = person(api, boss, "st@example.com", "editor")
    boss.put(f"/spaces/{space_id}/members/{viewer.id}", json={"role": "viewer"})

    for who, status in ((viewer, 403), (stranger, 404)):
        assert who.get(f"/spaces/{space_id}/benchmarks").status_code == status
        assert add_item(who, space_id, "x question", ORDERS).status_code == status
        assert (
            who.patch(
                f"/spaces/{space_id}/benchmarks/{item['id']}", json={"question": "yyy"}
            ).status_code
            == status
        )
        assert who.delete(f"/spaces/{space_id}/benchmarks/{item['id']}").status_code == status
        assert who.post(f"/spaces/{space_id}/benchmarks/runs", json={}).status_code == status
        assert who.get(f"/spaces/{space_id}/benchmarks/runs").status_code == status


# ── Scoring ──────────────────────────────────────────────────────────────────


def test_a_run_judges_each_answer_by_its_result_and_scores_them(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    for question, sql in (
        ("Revenue by region?", REVENUE),
        ("Revenue by region, again?", REVENUE),
        ("How many orders?", ORDERS),
        ("What is the revenue of the West?", REVENUE),
    ):
        assert add_item(boss, space_id, question, sql).status_code == 201
    llm = FakeLLM(
        benchmark_sql=[
            sql_plan(REVENUE_OTHER_WAY),  # same values, other names and column order: correct
            sql_plan(WRONG),  # it runs, but the numbers are wrong
            SqlPlan(action="clarify", clarification="Which year?"),  # asks instead of answering
            sql_plan("SELECT nope FROM sales"),  # never works
        ],
        benchmark_repair=[sql_plan("SELECT still_nope FROM sales")],
    )
    use(api, llm)

    run = run_all(boss, space_id)

    assert (run["status"], run["total"], run["done"]) == ("finished", 4, 4)
    assert (run["correct"], run["incorrect"], run["failed"]) == (1, 1, 2)
    assert run["accuracy"] == 0.25 and run["started_by_name"]
    results = {r["question"]: r for r in run["results"]}
    right = results["Revenue by region?"]
    assert (right["outcome"], right["attempts"], right["detail"]) == ("correct", 1, "")
    assert (
        right["generated_sql"] == REVENUE_OTHER_WAY
        and right["expected_rows"] == right["actual_rows"] == 4
    )
    wrong = results["Revenue by region, again?"]
    assert wrong["outcome"] == "incorrect" and "reference rows are missing" in wrong["detail"]
    asked = results["How many orders?"]
    assert asked["outcome"] == "not_a_query" and "clarifying question" in asked["detail"]
    broken = results["What is the revenue of the West?"]
    assert broken["outcome"] == "failed" and broken["attempts"] == 3 and "nope" in broken["detail"]
    assert all(r["duration_ms"] >= 0 for r in run["results"])
    assert (
        llm.purposes().count("benchmark_repair") == 2
    )  # two repairs for the one that never worked

    items = {
        i["question"]: i["last_outcome"] for i in boss.get(f"/spaces/{space_id}/benchmarks").json()
    }
    assert items["Revenue by region?"] == "correct" and items["How many orders?"] == "not_a_query"
    listed = boss.get(f"/spaces/{space_id}/benchmarks/runs").json()
    assert [r["id"] for r in listed] == [run["id"]] and listed[0]["accuracy"] == 0.25


def test_a_question_whose_reference_no_longer_runs_is_not_counted_against_the_assistant(
    api: TestClient,
) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    assert boss.upload(space_id, "staff.csv", customers_csv()).status_code == 201
    add_item(boss, space_id, "Revenue by region?", REVENUE)
    add_item(boss, space_id, "How many staff?", "SELECT count(*) AS n FROM staff")
    staff = next(t for t in boss.get(f"/spaces/{space_id}/tables").json() if t["name"] == "staff")
    assert boss.delete(f"/spaces/{space_id}/tables/{staff['id']}").status_code == 204
    use(api, FakeLLM(benchmark_sql=[sql_plan(REVENUE)]))

    run = run_all(boss, space_id)

    assert (run["correct"], run["reference_errors"], run["failed"]) == (1, 1, 0)
    assert run["accuracy"] == 1.0  # one judged, one right; the broken reference is set aside
    broken = next(r for r in run["results"] if r["outcome"] == "reference_error")
    assert "no longer runs" in broken["detail"] and broken["generated_sql"] is None


def test_a_run_can_try_only_some_questions(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    first = add_item(boss, space_id, "Revenue by region?", REVENUE).json()
    add_item(boss, space_id, "How many orders?", ORDERS)
    llm = FakeLLM(benchmark_sql=[sql_plan(REVENUE)])
    use(api, llm)

    run = run_all(boss, space_id, item_ids=[first["id"]])

    assert (run["total"], run["done"], run["correct"]) == (1, 1, 1)
    assert llm.purposes() == ["benchmark_sql"]  # nothing was asked about the other question


def test_a_run_needs_questions_and_an_ai_service(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    use(api, FakeLLM(benchmark_sql=[sql_plan(REVENUE)]))

    nothing = boss.post(f"/spaces/{space_id}/benchmarks/runs", json={})
    assert (nothing.status_code, code(nothing)) == (400, "no_benchmarks")

    add_item(boss, space_id, "Revenue by region?", REVENUE)
    off = FakeLLM()
    off.configured = False
    use(api, off)
    no_ai = boss.post(f"/spaces/{space_id}/benchmarks/runs", json={})
    assert (no_ai.status_code, code(no_ai)) == (400, "llm_not_configured")


def test_when_the_ai_service_is_down_the_run_stops_early_and_says_why(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    for i in range(5):
        add_item(boss, space_id, f"Revenue by region, version {i}?", REVENUE)
    use(
        api,
        FakeLLM(benchmark_sql=[LLMUnavailableError("All AI keys are resting.", retry_after=30)]),
    )

    run = run_all(boss, space_id)

    assert run["status"] == "failed" and "not responding" in run["error"]
    assert run["done"] == 3 and run["failed"] == 3  # it did not burn through the other two
    assert all("could not answer" in r["detail"] for r in run["results"])


def test_stored_results_never_quote_values_from_the_data(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    add_item(boss, space_id, "Revenue by region?", REVENUE)
    use(api, FakeLLM(benchmark_sql=[sql_plan(WRONG)]))

    run = run_all(boss, space_id)

    detail = run["results"][0]["detail"]
    for value in ("North", "South", "East", "West"):
        assert value not in detail


def test_only_one_run_goes_at_a_time_in_a_space(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    add_item(boss, space_id, "Revenue by region?", REVENUE)

    class Slow(FakeLLM):
        async def complete_json(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(1.0)
            return await super().complete_json(*args, **kwargs)

    use(api, Slow(benchmark_sql=[sql_plan(REVENUE)]))
    first = boss.post(f"/spaces/{space_id}/benchmarks/runs", json={})
    second = boss.post(f"/spaces/{space_id}/benchmarks/runs", json={})

    assert first.status_code == 202
    assert (second.status_code, code(second)) == (409, "run_active")
    assert wait_for(boss, space_id, first.json()["id"])["status"] == "finished"


def test_a_run_cut_short_by_a_restart_is_marked_failed(
    settings: Any, api: TestClient, sql: Any
) -> None:
    from app.db.session import create_engine, create_sessionmaker

    boss = admin(api)
    space_id = sales_space(boss)
    sql(
        "INSERT INTO benchmark_runs (id, space_id, status, total) "
        "VALUES (gen_random_uuid(), :space, 'running', 3)",
        {"space": space_id},
    )
    engine = create_engine(settings)

    async def restart() -> int:
        try:
            return await service.fail_interrupted_runs(create_sessionmaker(engine))
        finally:
            await engine.dispose()

    assert asyncio.run(restart()) == 1
    (run,) = boss.get(f"/spaces/{space_id}/benchmarks/runs").json()
    assert run["status"] == "failed" and "restarted" in run["error"]


def test_row_order_counts_only_for_questions_marked_as_rankings(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    top = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 2 DESC"
    plain = add_item(boss, space_id, "Revenue by region?", top).json()
    ranking = add_item(boss, space_id, "Rank the regions by revenue.", top, ordered=True).json()
    assert (plain["ordered"], ranking["ordered"]) == (False, True)
    same_rows_unsorted = "SELECT region, sum(amount) AS revenue FROM sales GROUP BY 1 ORDER BY 1"
    use(api, FakeLLM(benchmark_sql=[sql_plan(same_rows_unsorted)]))

    run = run_all(boss, space_id)

    by_question = {r["question"]: r for r in run["results"]}
    assert by_question["Revenue by region?"]["outcome"] == "correct"  # same rows, any order
    ranked = by_question["Rank the regions by revenue."]
    assert ranked["outcome"] == "incorrect" and "different order" in ranked["detail"]
    flipped = boss.patch(f"/spaces/{space_id}/benchmarks/{ranking['id']}", json={"ordered": False})
    assert flipped.json()["ordered"] is False


# ── Accuracy over time and the release gate ──────────────────────────────────


def scored_run(boss: Person, space_id: str, sql: str) -> dict[str, Any]:
    use(boss.api, FakeLLM(benchmark_sql=[sql_plan(sql)]))
    return run_all(boss, space_id)


def test_the_gate_fails_when_accuracy_drops_below_the_accepted_baseline(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    assert add_item(boss, space_id, "Revenue by region?", REVENUE).status_code == 201

    good = scored_run(boss, space_id, REVENUE)
    boss.put(f"/spaces/{space_id}/benchmarks/gate", json={"enabled": True})
    baseline = boss.put(f"/spaces/{space_id}/benchmarks/gate/baseline", json={"run_id": good["id"]})
    assert baseline.status_code == 200 and baseline.json()["baseline_accuracy"] == 1.0
    assert baseline.json()["result"] == "passed"

    scored_run(boss, space_id, WRONG)
    gate = boss.get(f"/spaces/{space_id}/benchmarks/gate").json()
    assert gate["result"] == "failed" and "below the baseline" in gate["reasons"][0]

    report = boss.get(f"/spaces/{space_id}/benchmarks/accuracy").json()
    assert [p["accuracy"] for p in report["points"]] == [1.0, 0.0]  # oldest first
    assert report["gate"]["result"] == "failed"

    allowed = boss.put(
        f"/spaces/{space_id}/benchmarks/gate", json={"enabled": True, "max_drop": 1}
    ).json()
    assert allowed["result"] == "passed"
    floor = boss.put(
        f"/spaces/{space_id}/benchmarks/gate",
        json={"enabled": True, "max_drop": 1, "min_accuracy": 0.5},
    ).json()
    assert floor["result"] == "failed" and "required" in floor["reasons"][0]
    off = boss.put(f"/spaces/{space_id}/benchmarks/gate", json={"enabled": False}).json()
    assert off["result"] == "skipped"


def test_the_gate_needs_a_finished_run_and_a_real_baseline(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    assert add_item(boss, space_id, "Revenue by region?", REVENUE).status_code == 201

    on = boss.put(f"/spaces/{space_id}/benchmarks/gate", json={"enabled": True}).json()
    assert on["result"] == "no_run"
    missing = boss.put(
        f"/spaces/{space_id}/benchmarks/gate/baseline",
        json={"run_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404
    bad = boss.put(f"/spaces/{space_id}/benchmarks/gate", json={"enabled": True, "max_drop": 2})
    assert bad.status_code == 422


def test_the_accuracy_overview_lists_the_spaces_the_person_can_edit(api: TestClient) -> None:
    boss = admin(api)
    space_id = sales_space(boss)
    assert add_item(boss, space_id, "Revenue by region?", REVENUE).status_code == 201
    scored_run(boss, space_id, REVENUE)
    scored_run(boss, space_id, WRONG)

    rows = {r["space_id"]: r for r in boss.get("/benchmarks/accuracy").json()}

    assert rows[space_id]["latest_accuracy"] == 0.0
    assert rows[space_id]["previous_accuracy"] == 1.0 and rows[space_id]["runs"] == 2
