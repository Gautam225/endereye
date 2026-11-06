"""Benchmark questions: a question with SQL known to answer it, scored against what the
assistant writes. Editors of the space only."""

import asyncio
import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.llm.gateway import LLMDep
from app.schemas.benchmarks import (
    AccuracyReport,
    BenchmarkItemCreate,
    BenchmarkItemOut,
    BenchmarkItemUpdate,
    GateBaseline,
    GateSettings,
    GateStatus,
    RunDetail,
    RunOut,
    RunStart,
    SpaceAccuracy,
)
from app.services import benchmarks as service
from app.services import spaces

router = APIRouter(prefix="/spaces/{space_id}/benchmarks", tags=["benchmarks"])
overview_router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])
NO_CONTENT = status.HTTP_204_NO_CONTENT


@overview_router.get("/accuracy", response_model=list[SpaceAccuracy])
async def accuracy_overview(user: CurrentUser, session: SessionDep) -> list[SpaceAccuracy]:
    """The latest score of every space the person can edit, to see where accuracy is slipping."""
    mine = await spaces.list_spaces(session, user)
    editable = [(s.id, s.name) for s in mine if s.my_role == "editor"]
    return await service.accuracy_overview(session, editable)


@router.get("", response_model=list[BenchmarkItemOut])
async def list_items(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[BenchmarkItemOut]:
    await spaces.get_access(session, user, space_id, edit=True)
    return await service.list_items(session, space_id)


@router.post("", response_model=BenchmarkItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    space_id: uuid.UUID,
    body: BenchmarkItemCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> BenchmarkItemOut:
    """Add a question and the SQL that answers it correctly. The SQL is checked and run now."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.create_item(session, access, user, body, settings)


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, limit: int = 20
) -> list[RunOut]:
    await spaces.get_access(session, user, space_id, edit=True)
    return await service.list_runs(session, space_id, limit)


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    space_id: uuid.UUID,
    body: RunStart,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
) -> RunOut:
    """Start scoring the assistant. The run goes on in the background; poll the run for
    progress. Each question costs one or more AI calls."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    tasks: set[asyncio.Task] = request.app.state.benchmark_tasks
    return await service.start_run(
        session,
        access,
        user,
        body.item_ids,
        sessionmaker=request.app.state.sessionmaker,
        settings=settings,
        llm=llm,
        tasks=tasks,
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    space_id: uuid.UUID, run_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> RunDetail:
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.get_run(session, access, run_id)


@router.get("/accuracy", response_model=AccuracyReport)
async def accuracy(space_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> AccuracyReport:
    """Score of each finished run over time, and whether the release gate passes."""
    await spaces.get_access(session, user, space_id, edit=True)
    return await service.accuracy_report(session, space_id)


@router.get("/gate", response_model=GateStatus)
async def get_gate(space_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> GateStatus:
    """Is the space fit to publish? `result` is `failed` when accuracy dropped."""
    await spaces.get_access(session, user, space_id, edit=True)
    return await service.gate_status(session, space_id)


@router.put("/gate", response_model=GateStatus)
async def put_gate(
    space_id: uuid.UUID, body: GateSettings, user: CurrentUser, session: SessionDep
) -> GateStatus:
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.update_gate(session, access, body)


@router.put("/gate/baseline", response_model=GateStatus)
async def put_baseline(
    space_id: uuid.UUID, body: GateBaseline, user: CurrentUser, session: SessionDep
) -> GateStatus:
    """Accept a finished run as the score that later changes must not fall below."""
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.set_baseline(session, access, body.run_id)


@router.patch("/{item_id}", response_model=BenchmarkItemOut)
async def update_item(
    space_id: uuid.UUID,
    item_id: uuid.UUID,
    body: BenchmarkItemUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> BenchmarkItemOut:
    access = await spaces.get_access(session, user, space_id, edit=True)
    return await service.update_item(session, access, item_id, body, settings)


@router.delete("/{item_id}", status_code=NO_CONTENT)
async def delete_item(
    space_id: uuid.UUID, item_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    access = await spaces.get_access(session, user, space_id, edit=True)
    await service.delete_item(session, access, item_id)
    return Response(status_code=NO_CONTENT)
