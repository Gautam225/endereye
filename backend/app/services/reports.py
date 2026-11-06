"""Scheduled reports: kept answers, run on a schedule, sent as PDF and/or Excel.

A report runs as the person who made it, through the same checks and access rules as a question
they asked themselves, so it only ever holds what they may read. If that person is disabled or
leaves the space, the report is switched off instead of running with someone else's rights.
"""

import asyncio
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import (
    Dashboard,
    DashboardItem,
    Report,
    ReportFormat,
    ReportItem,
    ReportRun,
    ReportRunStatus,
    User,
)
from app.schemas.dashboards import (
    ItemRef,
    ReportCreate,
    ReportOptions,
    ReportOut,
    ReportUpdate,
    RunOut,
)
from app.services import mail_config, mailer, notifications, spaces
from app.services.report_files import Section, build_pdf, build_xlsx
from app.services.schedule import next_run
from app.services.spaces import SpaceAccess

logger = logging.getLogger(__name__)

DUE_BATCH = 20  # reports started per look, so one busy minute can't start hundreds at once


# ── Options and checks ───────────────────────────────────────────────────────


async def options(session: AsyncSession, settings: Settings) -> ReportOptions:
    return ReportOptions(
        email_configured=await mail_config.is_configured(session, settings),
        allowed_domains=[d.lower() for d in settings.report_allowed_email_domains],
        max_recipients=settings.report_max_recipients,
    )


def check_recipients(recipients: list[str], settings: Settings) -> list[str]:
    """Lower-cased, without repeats; refuses too many, or domains the server does not allow."""
    unique = list(dict.fromkeys(r.strip().lower() for r in recipients))
    if len(unique) > settings.report_max_recipients:
        raise AppError(
            f"A report can go to at most {settings.report_max_recipients} people.",
            code="validation_error",
        )
    allowed = {d.lower().lstrip("@") for d in settings.report_allowed_email_domains}
    if allowed:
        blocked = [r for r in unique if r.rsplit("@", 1)[-1] not in allowed]
        if blocked:
            raise AppError(
                "Reports can only be sent to these domains: "
                f"{', '.join(sorted(allowed))}. Not allowed: {', '.join(blocked)}.",
                code="validation_error",
            )
    return unique


def _due(report: Report, after: datetime) -> datetime | None:
    if not report.enabled:
        return None
    return next_run(
        report.frequency,
        hour=report.hour,
        minute=report.minute,
        weekdays=report.weekdays,
        day_of_month=report.day_of_month,
        timezone=report.timezone,
        after=after,
    )


async def _own_items(
    session: AsyncSession, access: SpaceAccess, user: User, item_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """The kept answers must be the person's own, in this space. Order is kept."""
    unique = list(dict.fromkeys(item_ids))
    found = set(
        await session.scalars(
            select(DashboardItem.id)
            .join(Dashboard, Dashboard.id == DashboardItem.dashboard_id)
            .where(
                DashboardItem.id.in_(unique),
                Dashboard.owner_id == user.id,
                Dashboard.space_id == access.space.id,
            )
        )
    )
    if len(found) != len(unique):
        raise NotFoundError("One of those kept answers does not exist.")
    return unique


# ── CRUD ─────────────────────────────────────────────────────────────────────


async def _item_ids(session: AsyncSession, report_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(ReportItem.item_id)
            .where(ReportItem.report_id == report_id)
            .order_by(ReportItem.position)
        )
    )


async def _item_refs(session: AsyncSession, report_id: uuid.UUID) -> list[ItemRef]:
    rows = await session.execute(
        select(DashboardItem.id, DashboardItem.title)
        .join(ReportItem, ReportItem.item_id == DashboardItem.id)
        .where(ReportItem.report_id == report_id)
        .order_by(ReportItem.position)
    )
    return [ItemRef(id=i, title=t) for i, t in rows]


async def _out(session: AsyncSession, report: Report) -> ReportOut:
    last = await session.scalar(
        select(ReportRun)
        .where(ReportRun.report_id == report.id)
        .order_by(ReportRun.started_at.desc())
        .limit(1)
    )
    return ReportOut(
        id=report.id,
        space_id=report.space_id,
        name=report.name,
        item_ids=await _item_ids(session, report.id),
        frequency=report.frequency,  # type: ignore[arg-type]
        items=await _item_refs(session, report.id),
        hour=report.hour,
        minute=report.minute,
        weekdays=list(report.weekdays),
        day_of_month=report.day_of_month,
        timezone=report.timezone,
        format=report.format,  # type: ignore[arg-type]
        recipients=list(report.recipients),
        enabled=report.enabled,
        next_run_at=report.next_run_at,
        last_run_at=report.last_run_at,
        last_run=RunOut.model_validate(last) if last else None,
        created_at=report.created_at,
    )


async def list_reports(session: AsyncSession, access: SpaceAccess, user: User) -> list[ReportOut]:
    reports = await session.scalars(
        select(Report)
        .where(Report.space_id == access.space.id, Report.owner_id == user.id)
        .order_by(Report.created_at, Report.id)
    )
    return [await _out(session, r) for r in reports]


async def get_report(
    session: AsyncSession, access: SpaceAccess, user: User, report_id: uuid.UUID
) -> Report:
    report = await session.get(Report, report_id)
    if report is None or report.space_id != access.space.id or report.owner_id != user.id:
        raise NotFoundError("That report does not exist.")
    return report


async def _set_items(
    session: AsyncSession, report_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> None:
    await session.execute(delete(ReportItem).where(ReportItem.report_id == report_id))
    session.add_all(
        ReportItem(report_id=report_id, item_id=item_id, position=index)
        for index, item_id in enumerate(item_ids)
    )


async def create_report(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: ReportCreate,
    settings: Settings,
) -> ReportOut:
    held = await session.scalar(
        select(func.count()).select_from(Report).where(Report.owner_id == user.id)
    )
    if held >= settings.report_max_per_person:
        raise AppError(
            f"You can have at most {settings.report_max_per_person} reports.",
            code="too_many_reports",
        )
    item_ids = await _own_items(session, access, user, data.item_ids)
    report = Report(
        space_id=access.space.id,
        owner_id=user.id,
        name=data.name,
        frequency=data.frequency,
        hour=data.hour,
        minute=data.minute,
        weekday=data.weekdays[0],
        weekdays=list(data.weekdays),
        day_of_month=data.day_of_month,
        timezone=data.timezone,
        format=data.format,
        recipients=check_recipients(list(data.recipients), settings),
        enabled=data.enabled,
    )
    report.next_run_at = _due(report, datetime.now(UTC))
    session.add(report)
    await session.flush()
    await _set_items(session, report.id, item_ids)
    await session.commit()
    return await _out(session, report)


async def update_report(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    report: Report,
    data: ReportUpdate,
    settings: Settings,
) -> ReportOut:
    changes = data.model_dump(exclude_unset=True, exclude={"item_ids", "recipients"})
    for key, value in changes.items():
        if value is not None:
            setattr(report, key, value)
    if data.weekdays is not None:
        report.weekday = data.weekdays[0]
    if data.recipients is not None:
        report.recipients = check_recipients(list(data.recipients), settings)
    if data.item_ids is not None:
        await _set_items(session, report.id, await _own_items(session, access, user, data.item_ids))
    report.next_run_at = _due(report, datetime.now(UTC))
    await session.commit()
    return await _out(session, report)


async def delete_report(session: AsyncSession, report: Report, settings: Settings) -> None:
    await session.delete(report)
    await session.commit()
    shutil.rmtree(_folder(settings, report.id), ignore_errors=True)


# ── Runs ─────────────────────────────────────────────────────────────────────


def _folder(settings: Settings, report_id: uuid.UUID, run_id: uuid.UUID | None = None) -> Path:
    base = settings.data_path / "reports" / str(report_id)
    return base / str(run_id) if run_id else base


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "report"


async def list_runs(session: AsyncSession, report: Report, limit: int = 20) -> list[RunOut]:
    runs = await session.scalars(
        select(ReportRun)
        .where(ReportRun.report_id == report.id)
        .order_by(ReportRun.started_at.desc())
        .limit(min(limit, 100))
    )
    return [RunOut.model_validate(r) for r in runs]


async def get_run(session: AsyncSession, report: Report, run_id: uuid.UUID) -> ReportRun:
    run = await session.get(ReportRun, run_id)
    if run is None or run.report_id != report.id:
        raise NotFoundError("That run does not exist.")
    return run


def run_file(settings: Settings, run: ReportRun, name: str) -> Path:
    """A file of a run, by its name. The name must be one the run produced: it is never joined
    to the folder otherwise, so a crafted name can't point anywhere else."""
    if name not in run.files:
        raise NotFoundError("That file does not exist.")
    path = _folder(settings, run.report_id, run.id) / name
    if not path.is_file():
        raise NotFoundError("That file is no longer kept.")
    return path


async def start_run(
    session: AsyncSession,
    report: Report,
    trigger: str,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    tasks: set[asyncio.Task],
) -> ReportRun:
    running = await session.scalar(
        select(func.count())
        .select_from(ReportRun)
        .where(ReportRun.report_id == report.id, ReportRun.status == ReportRunStatus.RUNNING.value)
    )
    if running:
        raise ConflictError("This report is already being made.", code="run_active")
    run = ReportRun(report_id=report.id, trigger=trigger, status=ReportRunStatus.RUNNING.value)
    session.add(run)
    await session.commit()
    task = asyncio.create_task(execute_run(sessionmaker, settings, run.id))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return run


async def _sections(
    session: AsyncSession, access: SpaceAccess, items: list[DashboardItem], settings: Settings
) -> list[Section]:
    sections: list[Section] = []
    for item in items:
        section = Section(title=item.title, question=item.question)
        try:
            result = await spaces.run_sql(session, access, item.sql, settings)
        except AppError as exc:
            section.error = exc.message[:300]
        else:
            section.columns = [c.name for c in result.columns]
            section.rows = result.rows
            section.row_count = result.row_count
            section.truncated = result.truncated
        sections.append(section)
    return sections


async def _finish(
    session: AsyncSession,
    run: ReportRun,
    report: Report | None,
    status: ReportRunStatus,
    error: str = "",
) -> None:
    run.status = status.value
    run.error = error[:500]
    run.finished_at = datetime.now(UTC)
    if report is not None:
        report.last_run_at = run.finished_at
    await session.commit()


async def execute_run(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, run_id: uuid.UUID
) -> None:
    """Make the report's files, send them, and record how it went. Never raises."""
    async with sessionmaker() as session:
        run = await session.get(ReportRun, run_id)
        report = await session.get(Report, run.report_id) if run else None
        if run is None or report is None:
            return
        try:
            await _execute(session, settings, run, report)
            await _announce(session, report, run)
        except asyncio.CancelledError:
            await session.rollback()
            await _finish(session, run, report, ReportRunStatus.FAILED, "The app was stopped.")
            raise
        except Exception:
            logger.exception("Report %s failed", report.id)
            await session.rollback()
            await _finish(
                session, run, report, ReportRunStatus.FAILED, "Something went wrong on our side."
            )
        await _prune(session, report, settings)


async def _announce(session: AsyncSession, report: Report, run: ReportRun) -> None:
    """Tell the owner how the run went. A report they asked for by hand is announced too: they
    may have moved on to another page while it was being made."""
    place = f"/spaces/{report.space_id}/reports?report={report.id}"
    if run.status == ReportRunStatus.OK.value:
        sent = (
            f"Sent to {len(run.emailed_to)} {'person' if len(run.emailed_to) == 1 else 'people'}."
            if run.emailed_to
            else (run.error or "Ready to download.")
        )
        first = run.files[0] if run.files else None
        await notifications.notify(
            session,
            [report.owner_id],
            kind="report_ready",
            level="success",
            title=f"{report.name} is ready",
            body=sent,
            link=place,
            action=(
                {
                    "type": "download",
                    "label": "Download " + ("PDF" if first.endswith(".pdf") else "Excel"),
                    "path": (
                        f"/spaces/{report.space_id}/reports/{report.id}/runs/{run.id}/files/{first}"
                    ),
                    "filename": first,
                }
                if first
                else None
            ),
        )
    elif not report.enabled:
        await notifications.notify(
            session,
            [report.owner_id],
            kind="report_off",
            level="warning",
            title=f"{report.name} was switched off",
            body=run.error,
            link=place,
        )
    else:
        await notifications.notify(
            session,
            [report.owner_id],
            kind="report_failed",
            level="error",
            title=f"{report.name} failed",
            body=run.error,
            link=place,
        )


async def _execute(
    session: AsyncSession, settings: Settings, run: ReportRun, report: Report
) -> None:
    owner = await session.get(User, report.owner_id)
    if owner is None or not owner.is_active:
        report.enabled, report.next_run_at = False, None
        await _finish(
            session, run, report, ReportRunStatus.FAILED, "The owner can no longer sign in."
        )
        return
    try:
        access = await spaces.get_access(session, owner, report.space_id)
    except AppError:
        report.enabled, report.next_run_at = False, None
        await _finish(
            session,
            run,
            report,
            ReportRunStatus.FAILED,
            "The owner no longer has access to this space.",
        )
        return

    items = list(
        await session.scalars(
            select(DashboardItem)
            .join(ReportItem, ReportItem.item_id == DashboardItem.id)
            .where(ReportItem.report_id == report.id)
            .order_by(ReportItem.position)
        )
    )
    if not items:
        await _finish(
            session, run, report, ReportRunStatus.FAILED, "The report has no kept answers."
        )
        return
    sections = await _sections(session, access, items, settings)
    if all(s.error for s in sections):
        await _finish(
            session,
            run,
            report,
            ReportRunStatus.FAILED,
            f"No answer could be run: {sections[0].error}",
        )
        return

    now = datetime.now(UTC)
    stem = f"{_slug(report.name)}-{now.strftime('%Y-%m-%d')}"
    files: dict[str, bytes] = {}
    if report.format in (ReportFormat.PDF.value, ReportFormat.BOTH.value):
        files[f"{stem}.pdf"] = await asyncio.to_thread(
            build_pdf, report.name, sections, now, max_rows=settings.report_pdf_rows
        )
    if report.format in (ReportFormat.XLSX.value, ReportFormat.BOTH.value):
        files[f"{stem}.xlsx"] = await asyncio.to_thread(build_xlsx, report.name, sections, now)
    folder = _folder(settings, report.id, run.id)
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_bytes(content)
    run.files = list(files)

    note = ""
    failed = [s for s in sections if s.error]
    if failed:
        note = f"{len(failed)} of {len(sections)} answers could not be run."
    recipients = list(report.recipients)
    if recipients:
        recipients = check_recipients(recipients, settings)  # the rules may have changed since
        if not await mail_config.is_configured(session, settings):
            note = (note + " Not emailed: email is not set up on this server.").strip()
        else:
            body = (
                f'Your report "{report.name}" is attached.\n\n'
                f"Made on {now.strftime('%Y-%m-%d %H:%M UTC')} from {len(sections)} kept "
                f"answer{'s' if len(sections) != 1 else ''}.\n"
                "It was set up in Eye of Ender and contains what its owner may see.\n"
            )
            try:
                await mail_config.deliver(
                    session,
                    settings,
                    recipients,
                    f"{report.name} - {now.strftime('%Y-%m-%d')}",
                    body,
                    [mailer.Attachment(name, content) for name, content in files.items()],
                )
            except mailer.MailError as exc:
                await notifications.email_problem(session, str(exc))
                await _finish(session, run, report, ReportRunStatus.FAILED, f"Email failed: {exc}")
                return
            run.emailed_to = recipients
    await _finish(session, run, report, ReportRunStatus.OK, note)


async def _prune(session: AsyncSession, report: Report, settings: Settings) -> None:
    """Keep the newest few runs and their files."""
    old = list(
        await session.scalars(
            select(ReportRun)
            .where(ReportRun.report_id == report.id)
            .order_by(ReportRun.started_at.desc())
            .offset(settings.report_keep_runs)
        )
    )
    for run in old:
        shutil.rmtree(_folder(settings, report.id, run.id), ignore_errors=True)
        await session.delete(run)
    if old:
        await session.commit()


# ── The scheduler ────────────────────────────────────────────────────────────


async def run_due(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    tasks: set[asyncio.Task],
    now: datetime | None = None,
) -> int:
    """Start every report that is due. A report is claimed by moving its next time forward in
    one UPDATE, so two servers sharing the database never start the same one twice."""
    now = now or datetime.now(UTC)
    started = 0
    async with sessionmaker() as session:
        due = list(
            await session.scalars(
                select(Report)
                .where(Report.enabled.is_(True), Report.next_run_at <= now)
                .order_by(Report.next_run_at)
                .limit(DUE_BATCH)
            )
        )
        for report in due:
            following = _due(report, now)
            claimed = await session.execute(
                update(Report)
                .where(Report.id == report.id, Report.next_run_at == report.next_run_at)
                .values(next_run_at=following)
            )
            await session.commit()
            if not claimed.rowcount:
                continue
            try:
                await start_run(
                    session,
                    report,
                    "schedule",
                    sessionmaker=sessionmaker,
                    settings=settings,
                    tasks=tasks,
                )
                started += 1
            except ConflictError:
                logger.info("Report %s is still running; skipping this time", report.id)
    return started


async def fail_interrupted_runs(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """Runs left 'running' by a restart will never finish: say so."""
    async with sessionmaker() as session:
        result = await session.execute(
            update(ReportRun)
            .where(ReportRun.status == ReportRunStatus.RUNNING.value)
            .values(
                status=ReportRunStatus.FAILED.value,
                error="The app restarted while this report was being made.",
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()
        return result.rowcount or 0
