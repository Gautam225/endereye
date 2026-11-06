"""Benchmark questions of a space, and starting runs that score the assistant on them."""

import asyncio
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.benchmark_runner import MAX_COMPARED_ROWS, run_benchmark
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    BenchmarkGate,
    BenchmarkItem,
    BenchmarkResult,
    BenchmarkRun,
    RunStatus,
    User,
)
from app.llm.gateway import LLMGateway
from app.schemas.benchmarks import (
    AccuracyPoint,
    AccuracyReport,
    BenchmarkItemCreate,
    BenchmarkItemOut,
    BenchmarkItemUpdate,
    GateSettings,
    GateStatus,
    ResultOut,
    RunDetail,
    RunOut,
    SpaceAccuracy,
)
from app.services import engines
from app.services.spaces import SpaceAccess

logger = logging.getLogger(__name__)

RECENT_RUNS_FOR_STATUS = 5
ACCURACY_HISTORY = 100


# ── Questions ────────────────────────────────────────────────────────────────


async def _check_reference(
    session: AsyncSession, space_id: uuid.UUID, sql: str, settings: Settings
) -> str:
    """The reference SQL must pass the guard and really run, with a result small enough to
    compare in full. A benchmark whose reference is wrong would score the assistant wrongly."""
    engine = await engines.for_space(session, space_id, settings)
    checked = engine.check(sql)
    try:
        result = await engine.run(
            session,
            checked,
            max_rows=MAX_COMPARED_ROWS,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except AppError as exc:
        raise AppError(
            f"The reference SQL does not run on this space's data: {exc.message}",
            code="validation_error",
        ) from None
    if result.truncated:
        raise AppError(
            f"The reference SQL returns more than {MAX_COMPARED_ROWS:,} rows. A benchmark answer "
            "must be small enough to compare in full: use an aggregate or a LIMIT.",
            code="validation_error",
        )
    return checked.display


async def list_items(session: AsyncSession, space_id: uuid.UUID) -> list[BenchmarkItemOut]:
    items = list(
        await session.scalars(
            select(BenchmarkItem)
            .where(BenchmarkItem.space_id == space_id)
            .order_by(BenchmarkItem.created_at, BenchmarkItem.id)
        )
    )
    latest = await _latest_outcomes(session, space_id)
    return [
        BenchmarkItemOut.model_validate(item).model_copy(
            update={"last_outcome": latest.get(item.id)}
        )
        for item in items
    ]


async def _latest_outcomes(session: AsyncSession, space_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """For each question, how it did in the most recent of the last few runs that tried it."""
    run_ids = list(
        await session.scalars(
            select(BenchmarkRun.id)
            .where(BenchmarkRun.space_id == space_id)
            .order_by(BenchmarkRun.started_at.desc())
            .limit(RECENT_RUNS_FOR_STATUS)
        )
    )
    if not run_ids:
        return {}
    rows = await session.execute(
        select(BenchmarkResult.item_id, BenchmarkResult.outcome, BenchmarkRun.started_at)
        .join(BenchmarkRun, BenchmarkRun.id == BenchmarkResult.run_id)
        .where(BenchmarkResult.run_id.in_(run_ids), BenchmarkResult.item_id.is_not(None))
        .order_by(BenchmarkRun.started_at.asc())
    )
    return {item_id: outcome for item_id, outcome, _ in rows}  # later runs overwrite earlier


async def create_item(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: BenchmarkItemCreate,
    settings: Settings,
) -> BenchmarkItemOut:
    count = await session.scalar(
        select(func.count())
        .select_from(BenchmarkItem)
        .where(BenchmarkItem.space_id == access.space.id)
    )
    if count >= settings.benchmark_max_items:
        raise AppError(
            f"A space can have at most {settings.benchmark_max_items} benchmark questions.",
            code="too_many_benchmarks",
        )
    sql = await _check_reference(session, access.space.id, data.expected_sql, settings)
    item = BenchmarkItem(
        space_id=access.space.id,
        question=data.question,
        expected_sql=sql,
        ordered=data.ordered,
        created_by=user.id,
    )
    session.add(item)
    await session.commit()
    return BenchmarkItemOut.model_validate(item)


async def _get_item(
    session: AsyncSession, access: SpaceAccess, item_id: uuid.UUID
) -> BenchmarkItem:
    item = await session.get(BenchmarkItem, item_id)
    if item is None or item.space_id != access.space.id:
        raise NotFoundError("That benchmark question does not exist in this space.")
    return item


async def update_item(
    session: AsyncSession,
    access: SpaceAccess,
    item_id: uuid.UUID,
    data: BenchmarkItemUpdate,
    settings: Settings,
) -> BenchmarkItemOut:
    item = await _get_item(session, access, item_id)
    if data.question is not None:
        item.question = data.question
    if data.ordered is not None:
        item.ordered = data.ordered
    if data.expected_sql is not None:
        item.expected_sql = await _check_reference(
            session, access.space.id, data.expected_sql, settings
        )
    await session.commit()
    return BenchmarkItemOut.model_validate(item)


async def delete_item(session: AsyncSession, access: SpaceAccess, item_id: uuid.UUID) -> None:
    await session.delete(await _get_item(session, access, item_id))
    await session.commit()


# ── Runs ─────────────────────────────────────────────────────────────────────


async def start_run(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    item_ids: list[uuid.UUID] | None,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    llm: LLMGateway,
    tasks: set[asyncio.Task],
) -> RunOut:
    if not llm.configured:
        raise AppError(
            "No AI service is configured, so benchmarks can't run. Add keys in .env.",
            code="llm_not_configured",
        )
    running = await session.scalar(
        select(func.count())
        .select_from(BenchmarkRun)
        .where(
            BenchmarkRun.space_id == access.space.id,
            BenchmarkRun.status == RunStatus.RUNNING.value,
        )
    )
    if running:
        raise ConflictError("A benchmark run is already going in this space.", code="run_active")

    query = select(BenchmarkItem.id).where(BenchmarkItem.space_id == access.space.id)
    if item_ids is not None:
        query = query.where(BenchmarkItem.id.in_(item_ids))
    chosen = list(await session.scalars(query))
    if not chosen:
        raise AppError("There are no benchmark questions to run.", code="no_benchmarks")

    run = BenchmarkRun(
        space_id=access.space.id,
        started_by=user.id,
        status=RunStatus.RUNNING.value,
        total=len(chosen),
    )
    session.add(run)
    await session.commit()

    task = asyncio.create_task(run_benchmark(sessionmaker, settings, llm, run.id, chosen))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return await _run_out(session, run)


async def _run_out(session: AsyncSession, run: BenchmarkRun) -> RunOut:
    starter = await session.get(User, run.started_by) if run.started_by else None
    out = RunOut.model_validate(run)
    return out.model_copy(update={"started_by_name": starter.full_name if starter else None})


async def list_runs(session: AsyncSession, space_id: uuid.UUID, limit: int = 20) -> list[RunOut]:
    runs = list(
        await session.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.space_id == space_id)
            .order_by(BenchmarkRun.started_at.desc())
            .limit(min(limit, 100))
        )
    )
    return [await _run_out(session, run) for run in runs]


async def get_run(session: AsyncSession, access: SpaceAccess, run_id: uuid.UUID) -> RunDetail:
    run = await session.get(BenchmarkRun, run_id)
    if run is None or run.space_id != access.space.id:
        raise NotFoundError("That benchmark run does not exist in this space.")
    await session.refresh(run)
    results = await session.scalars(
        select(BenchmarkResult)
        .where(BenchmarkResult.run_id == run.id)
        .order_by(BenchmarkResult.position)
    )
    base = await _run_out(session, run)
    return RunDetail(
        **base.model_dump(exclude={"accuracy"}),
        results=[ResultOut.model_validate(r) for r in results],
    )


async def fail_interrupted_runs(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """Runs left 'running' by a restart will never finish: mark them so the screen is honest."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    async with sessionmaker() as session:
        result = await session.execute(
            update(BenchmarkRun)
            .where(BenchmarkRun.status == RunStatus.RUNNING.value)
            .values(
                status=RunStatus.FAILED.value,
                error="The app restarted while this run was going.",
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()
        return result.rowcount or 0


# ── Accuracy over time and the release gate ──────────────────────────────────


def _accuracy(run: BenchmarkRun) -> float | None:
    judged = run.done - run.reference_errors
    return round(run.correct / judged, 4) if judged > 0 else None


async def _finished_runs(
    session: AsyncSession, space_id: uuid.UUID, limit: int
) -> list[BenchmarkRun]:
    """Newest first. A run stopped early (failed) has no trustworthy score, so it is left out."""
    return list(
        await session.scalars(
            select(BenchmarkRun)
            .where(
                BenchmarkRun.space_id == space_id,
                BenchmarkRun.status == RunStatus.FINISHED.value,
            )
            .order_by(BenchmarkRun.started_at.desc())
            .limit(limit)
        )
    )


def _judge(
    gate: BenchmarkGate | None, latest: BenchmarkRun | None, baseline: BenchmarkRun | None
) -> GateStatus:
    latest_accuracy = _accuracy(latest) if latest else None
    baseline_accuracy = _accuracy(baseline) if baseline else None
    status = GateStatus(
        enabled=gate.enabled if gate else False,
        max_drop=gate.max_drop if gate else 0.0,
        min_accuracy=gate.min_accuracy if gate else None,
        baseline_run_id=baseline.id if baseline else None,
        baseline_accuracy=baseline_accuracy,
        latest_run_id=latest.id if latest else None,
        latest_accuracy=latest_accuracy,
        result="skipped",
    )
    if not status.enabled:
        return status
    if latest_accuracy is None:
        status.result = "no_run"
        status.reasons = ["No finished benchmark run has judged any question yet."]
        return status
    reasons: list[str] = []
    if baseline_accuracy is not None and latest_accuracy < baseline_accuracy - status.max_drop:
        allowed = f" (allowed drop {status.max_drop:.1%})" if status.max_drop else ""
        reasons.append(
            f"Accuracy is {latest_accuracy:.1%}, below the baseline of "
            f"{baseline_accuracy:.1%}{allowed}."
        )
    if status.min_accuracy is not None and latest_accuracy < status.min_accuracy:
        reasons.append(
            f"Accuracy is {latest_accuracy:.1%}, below the required {status.min_accuracy:.1%}."
        )
    status.result = "failed" if reasons else "passed"
    status.reasons = reasons
    return status


async def gate_status(session: AsyncSession, space_id: uuid.UUID) -> GateStatus:
    gate = await session.get(BenchmarkGate, space_id)
    latest = next(iter(await _finished_runs(session, space_id, 1)), None)
    baseline = (
        await session.get(BenchmarkRun, gate.baseline_run_id)
        if gate and gate.baseline_run_id
        else None
    )
    return _judge(gate, latest, baseline)


async def accuracy_report(session: AsyncSession, space_id: uuid.UUID) -> AccuracyReport:
    runs = await _finished_runs(session, space_id, ACCURACY_HISTORY)
    points = [
        AccuracyPoint(
            run_id=r.id,
            at=r.started_at,
            accuracy=_accuracy(r),
            correct=r.correct,
            judged=r.done - r.reference_errors,
        )
        for r in reversed(runs)
    ]
    return AccuracyReport(points=points, gate=await gate_status(session, space_id))


async def _gate_for_update(session: AsyncSession, space_id: uuid.UUID) -> BenchmarkGate:
    gate = await session.get(BenchmarkGate, space_id)
    if gate is None:
        gate = BenchmarkGate(space_id=space_id, enabled=False, max_drop=0.0)
        session.add(gate)
    return gate


async def update_gate(session: AsyncSession, access: SpaceAccess, data: GateSettings) -> GateStatus:
    gate = await _gate_for_update(session, access.space.id)
    gate.enabled = data.enabled
    gate.max_drop = data.max_drop
    gate.min_accuracy = data.min_accuracy
    await session.commit()
    return await gate_status(session, access.space.id)


async def set_baseline(session: AsyncSession, access: SpaceAccess, run_id: uuid.UUID) -> GateStatus:
    """Accept a finished run as the score that later changes must not fall below."""
    run = await session.get(BenchmarkRun, run_id)
    if run is None or run.space_id != access.space.id:
        raise NotFoundError("That benchmark run does not exist in this space.")
    if run.status != RunStatus.FINISHED.value or _accuracy(run) is None:
        raise AppError(
            "Only a finished run that judged at least one question can be the baseline.",
            code="validation_error",
        )
    gate = await _gate_for_update(session, access.space.id)
    gate.baseline_run_id = run.id
    await session.commit()
    return await gate_status(session, access.space.id)


async def accuracy_overview(
    session: AsyncSession, spaces: list[tuple[uuid.UUID, str]]
) -> list[SpaceAccuracy]:
    """Latest and previous score of each given space, for the cross-space dashboard."""
    out: list[SpaceAccuracy] = []
    for space_id, name in spaces:
        runs = await _finished_runs(session, space_id, 2)
        out.append(
            SpaceAccuracy(
                space_id=space_id,
                space_name=name,
                latest_accuracy=_accuracy(runs[0]) if runs else None,
                previous_accuracy=_accuracy(runs[1]) if len(runs) > 1 else None,
                runs=len(runs),
                gate_result=(await gate_status(session, space_id)).result,
            )
        )
    return out
