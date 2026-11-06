"""Scoring the assistant against a space's benchmark questions.

For each question: run the reference SQL, let the assistant write its own SQL the way it does in
a chat (same context, same SQL guard, same repair attempts), run that, and compare the two
*results* (see benchmark_compare). The assistant sees nothing of the reference.

Runs are slow and each question costs AI calls, so a run is a background task whose progress is
saved after every question. Result rows are only compared here, never sent to the AI service,
and the stored detail never quotes a value.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.benchmark_compare import compare_results
from app.chat.context import build_context
from app.chat.pipeline import MAX_ATTEMPTS
from app.chat.prompts import SqlPlan, repair_messages, sql_messages
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import BenchmarkItem, BenchmarkResult, BenchmarkRun, Outcome, RunStatus
from app.engine.duckdb_engine import QueryFailedError, QueryResult
from app.engine.sql_guard import SqlNotAllowedError
from app.llm.errors import LLMError
from app.llm.gateway import LLMGateway
from app.services import engines, indexing, notifications

logger = logging.getLogger(__name__)

MAX_COMPARED_ROWS = 1000  # a benchmark answer must be small enough to compare in full
DETAIL_LENGTH = 300
LLM_FAILURES_BEFORE_ABORT = 3

ACTION_TEXT = {
    "clarify": "asked a clarifying question",
    "answer": "answered from documents",
    "describe": "described the data",
    "chat": "answered as a general question",
    "decline": "declined",
}


@dataclass(slots=True)
class Attempt:
    """The assistant's try at a question. `result` is set when its SQL ran; otherwise `outcome`
    and `detail` say why not."""

    outcome: Outcome | None = None
    detail: str = ""
    sql: str | None = None
    attempts: int = 0
    result: QueryResult | None = None


async def write_and_run(
    session: AsyncSession,
    space_id: uuid.UUID,
    question: str,
    settings: Settings,
    llm: LLMGateway,
    engine: engines.SpaceEngine,
) -> Attempt:
    """The assistant's own answer to a question, as SQL and its result."""
    embedder = await indexing.load_embedder(settings)
    reranker = await indexing.load_reranker(settings)
    built = await build_context(
        session, space_id, question, embedder=embedder, reranker=reranker, settings=settings
    )
    base = sql_messages(built.context, [], question, dialect=engine.dialect)
    plan, _ = await llm.complete_json(base, SqlPlan, purpose="benchmark_sql", tier="smart")

    sql: str | None = None
    problem = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if plan.action != "sql":
            what = ACTION_TEXT.get(plan.action, plan.action)
            return Attempt(
                Outcome.NOT_A_QUERY,
                f"The assistant {what} instead of writing a query.",
                sql,
                attempt,
            )
        sql = (plan.sql or "").strip()
        try:
            checked = engine.check(sql, set(built.table_names))
            result = await engine.run(
                session,
                checked,
                max_rows=MAX_COMPARED_ROWS,
                timeout_seconds=settings.query_timeout_seconds,
            )
            return Attempt(None, "", checked.display, attempt, result)
        except (SqlNotAllowedError, QueryFailedError) as exc:
            problem = exc.message
        if attempt == MAX_ATTEMPTS:
            break
        plan, _ = await llm.complete_json(
            repair_messages(base, plan, problem), SqlPlan, purpose="benchmark_repair", tier="smart"
        )
    return Attempt(Outcome.FAILED, problem[:DETAIL_LENGTH], sql, MAX_ATTEMPTS)


async def judge(
    session: AsyncSession,
    space_id: uuid.UUID,
    item: BenchmarkItem,
    settings: Settings,
    llm: LLMGateway,
    engine: engines.SpaceEngine,
) -> tuple[Outcome, str, str | None, int, int | None, int | None]:
    """(outcome, detail, the assistant's SQL, attempts, reference rows, the assistant's rows)."""
    try:
        reference = await engine.run(
            session,
            engine.check(item.expected_sql),
            max_rows=MAX_COMPARED_ROWS,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except AppError as exc:
        return (
            Outcome.REFERENCE_ERROR,
            f"The reference SQL no longer runs: {exc.message}"[:DETAIL_LENGTH],
            None,
            0,
            None,
            None,
        )
    if reference.truncated:
        return (
            Outcome.REFERENCE_ERROR,
            f"The reference SQL returns more than {MAX_COMPARED_ROWS:,} rows; use a smaller one.",
            None,
            0,
            None,
            None,
        )

    try:
        answer = await write_and_run(session, space_id, item.question, settings, llm, engine)
    except LLMError:
        raise  # the run decides what to do when the AI service is down
    except AppError as exc:
        return Outcome.FAILED, exc.message[:DETAIL_LENGTH], None, 0, len(reference.rows), None
    if answer.result is None:
        outcome = answer.outcome or Outcome.FAILED
        return outcome, answer.detail, answer.sql, answer.attempts, len(reference.rows), None

    verdict = compare_results(reference, answer.result, ordered=item.ordered)
    return (
        Outcome.CORRECT if verdict.correct else Outcome.INCORRECT,
        verdict.reason,
        answer.sql,
        answer.attempts,
        len(reference.rows),
        len(answer.result.rows),
    )


async def run_benchmark(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    llm: LLMGateway,
    run_id: uuid.UUID,
    item_ids: list[uuid.UUID],
) -> None:
    """Works through the questions, saving each result as it comes. Never raises."""
    async with sessionmaker() as session:
        run = await session.get(BenchmarkRun, run_id)
        if run is None:
            return
        status, error = RunStatus.FINISHED, ""
        try:
            engine = await engines.for_space(session, run.space_id, settings)
            items = list(
                await session.scalars(
                    select(BenchmarkItem)
                    .where(BenchmarkItem.id.in_(item_ids))
                    .order_by(BenchmarkItem.created_at, BenchmarkItem.id)
                )
            )
            llm_failures = 0
            for position, item in enumerate(items):
                started = time.perf_counter()
                try:
                    outcome, detail, sql, attempts, wanted, got = await judge(
                        session, run.space_id, item, settings, llm, engine
                    )
                    llm_failures = 0
                except LLMError as exc:
                    llm_failures += 1
                    outcome, detail, sql, attempts, wanted, got = (
                        Outcome.FAILED,
                        f"The AI service could not answer: {exc.message}"[:DETAIL_LENGTH],
                        None,
                        0,
                        None,
                        None,
                    )
                await _record(
                    session,
                    run,
                    position,
                    item,
                    outcome,
                    detail,
                    sql,
                    attempts,
                    wanted,
                    got,
                    started,
                )
                if llm_failures >= LLM_FAILURES_BEFORE_ABORT:
                    status, error = (
                        RunStatus.FAILED,
                        "The AI service is not responding. Try again later.",
                    )
                    break
        except asyncio.CancelledError:
            status, error = RunStatus.FAILED, "The run was interrupted."
            raise
        except Exception as exc:
            logger.exception("Benchmark run failed")
            status = RunStatus.FAILED
            error = (
                exc.message[:DETAIL_LENGTH]
                if isinstance(exc, AppError)
                else "The run stopped because of an internal error."
            )
        finally:
            with contextlib.suppress(Exception):
                await asyncio.shield(_finish(sessionmaker, run_id, status, error))


async def _record(
    session: AsyncSession,
    run: BenchmarkRun,
    position: int,
    item: BenchmarkItem,
    outcome: Outcome,
    detail: str,
    sql: str | None,
    attempts: int,
    wanted: int | None,
    got: int | None,
    started: float,
) -> None:
    session.add(
        BenchmarkResult(
            run_id=run.id,
            item_id=item.id,
            position=position,
            question=item.question,
            expected_sql=item.expected_sql,
            generated_sql=sql,
            outcome=outcome.value,
            detail=detail,
            attempts=attempts,
            expected_rows=wanted,
            actual_rows=got,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    )
    run.done += 1
    match outcome:
        case Outcome.CORRECT:
            run.correct += 1
        case Outcome.INCORRECT:
            run.incorrect += 1
        case Outcome.REFERENCE_ERROR:
            run.reference_errors += 1
        case _:
            run.failed += 1
    await session.commit()


async def _finish(
    sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, status: RunStatus, error: str
) -> None:
    async with sessionmaker() as session:
        await session.execute(
            update(BenchmarkRun)
            .where(BenchmarkRun.id == run_id)
            .values(status=status.value, error=error, finished_at=datetime.now(UTC))
        )
        await session.commit()
        run = await session.get(BenchmarkRun, run_id)
        if run is not None:
            judged = run.done - run.reference_errors
            score = f"{round(100 * run.correct / judged)}% correct" if judged > 0 else "no score"
            finished = status == RunStatus.FINISHED
            await notifications.notify(
                session,
                [run.started_by],
                kind="benchmark_finished" if finished else "benchmark_failed",
                level="success" if finished else "error",
                title=f"Benchmark finished: {score}" if finished else "Benchmark stopped early",
                body=(f"{run.correct} of {judged} answers matched." if finished else error)[:300],
                link=f"/spaces/{run.space_id}?tab=benchmarks",
            )
