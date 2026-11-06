"""Scheduled reports: kept answers sent as a PDF and/or Excel file on a schedule. A report runs as
its owner and is private to them."""

import uuid

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, SettingsDep
from app.db.session import SessionDep
from app.schemas.dashboards import (
    ReportCreate,
    ReportOptions,
    ReportOut,
    ReportUpdate,
    RunOut,
)
from app.services import reports as service
from app.services import spaces

router = APIRouter(prefix="/spaces/{space_id}/reports", tags=["reports"])
NO_CONTENT = status.HTTP_204_NO_CONTENT

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/options", response_model=ReportOptions)
async def report_options(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> ReportOptions:
    await spaces.get_access(session, user, space_id)
    return await service.options(session, settings)


@router.get("", response_model=list[ReportOut])
async def list_reports(
    space_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[ReportOut]:
    access = await spaces.get_access(session, user, space_id)
    return await service.list_reports(session, access, user)


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    space_id: uuid.UUID,
    body: ReportCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    access = await spaces.get_access(session, user, space_id)
    return await service.create_report(session, access, user, body, settings)


@router.patch("/{report_id}", response_model=ReportOut)
async def update_report(
    space_id: uuid.UUID,
    report_id: uuid.UUID,
    body: ReportUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ReportOut:
    access = await spaces.get_access(session, user, space_id)
    report = await service.get_report(session, access, user, report_id)
    return await service.update_report(session, access, user, report, body, settings)


@router.delete("/{report_id}", status_code=NO_CONTENT)
async def delete_report(
    space_id: uuid.UUID,
    report_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    access = await spaces.get_access(session, user, space_id)
    report = await service.get_report(session, access, user, report_id)
    await service.delete_report(session, report, settings)
    return Response(status_code=NO_CONTENT)


@router.post("/{report_id}/run", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_now(
    space_id: uuid.UUID,
    report_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> RunOut:
    """Make the report now, outside its schedule. It is sent to the recipients like any other
    run. The run goes on in the background; poll `runs` for how it went."""
    access = await spaces.get_access(session, user, space_id)
    report = await service.get_report(session, access, user, report_id)
    run = await service.start_run(
        session,
        report,
        "manual",
        sessionmaker=request.app.state.sessionmaker,
        settings=settings,
        tasks=request.app.state.report_tasks,
    )
    return RunOut.model_validate(run)


@router.get("/{report_id}/runs", response_model=list[RunOut])
async def list_runs(
    space_id: uuid.UUID, report_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[RunOut]:
    access = await spaces.get_access(session, user, space_id)
    report = await service.get_report(session, access, user, report_id)
    return await service.list_runs(session, report)


@router.get("/{report_id}/runs/{run_id}/files/{name}")
async def download_file(
    space_id: uuid.UUID,
    report_id: uuid.UUID,
    run_id: uuid.UUID,
    name: str,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> FileResponse:
    access = await spaces.get_access(session, user, space_id)
    report = await service.get_report(session, access, user, report_id)
    run = await service.get_run(session, report, run_id)
    path = service.run_file(settings, run, name)
    return FileResponse(
        path,
        media_type=CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
        filename=path.name,
    )
