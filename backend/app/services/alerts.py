"""Alerts: "tell me when failed orders go above 3%".

An alert watches one number (the first number of a kept answer, or a shared metric worked out on
its table) and compares it with a threshold on a schedule. It runs as its owner, through the
same checks and access rules as a question they asked themselves, so it never reads more than
they may; if the owner loses access it is switched off.

To keep the inbox quiet, a person is told when the condition starts to hold, again only after
`renotify_hours` while it still holds (0 means never again), and once when it ends. Not every
check.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.charts import is_numeric
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.db.models import (
    Alert,
    AlertEvent,
    AlertSource,
    AlertState,
    Dashboard,
    DashboardItem,
    SqlExpression,
    User,
)
from app.schemas.alerts import AlertCreate, AlertEventOut, AlertOut, AlertUpdate
from app.services import expressions, mail_config, mailer, notifications, reports, spaces
from app.services.spaces import SpaceAccess

logger = logging.getLogger(__name__)

MAX_EVENTS = 50  # kept per alert
DUE_BATCH = 50

SYMBOL = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤"}
WORDS = {"gt": "above", "gte": "at least", "lt": "below", "lte": "at most"}
WORDS_OF = {"gt": "goes above", "gte": "reaches", "lt": "goes below", "lte": "falls to"}


def holds(value: float, operator: str, threshold: float) -> bool:
    return {
        "gt": value > threshold,
        "gte": value >= threshold,
        "lt": value < threshold,
        "lte": value <= threshold,
    }[operator]


def describe(alert: Alert) -> str:
    return f"{alert.name} is {WORDS[alert.operator]} {alert.threshold:g}"


# ── The number being watched ─────────────────────────────────────────────────


def _to_number(value: object) -> float:
    if isinstance(value, bool) or value is None:
        raise AppError("The query gave no number.", code="invalid_alert")
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise AppError(
            "The query gave something that is not a number.", code="invalid_alert"
        ) from None


async def current_value(
    session: AsyncSession, access: SpaceAccess, alert: Alert, settings: Settings
) -> float:
    """The watched number right now, as the owner may read the data."""
    if alert.source_type == AlertSource.ITEM.value:
        item = await session.get(DashboardItem, alert.item_id) if alert.item_id else None
        if item is None:
            raise AppError("The kept answer this alert watched was removed.", code="invalid_alert")
        result = await spaces.run_sql(session, access, item.sql, settings)
        if not result.rows:
            raise AppError("The query returned no rows.", code="invalid_alert")
        names = [c.name for c in result.columns]
        if alert.value_column:
            if alert.value_column not in names:
                raise AppError(
                    f"The query has no column called '{alert.value_column}'.", code="invalid_alert"
                )
            index = names.index(alert.value_column)
        else:
            numeric = [i for i, c in enumerate(result.columns) if is_numeric(c.type)]
            if not numeric:
                raise AppError("The query has no number column to watch.", code="invalid_alert")
            index = numeric[0]
        return _to_number(result.rows[0][index])

    metric = await session.get(SqlExpression, alert.expression_id) if alert.expression_id else None
    if metric is None or metric.space_id != alert.space_id:
        raise AppError("The metric this alert watched was removed.", code="invalid_alert")
    if metric.table_name is None:
        raise AppError("The metric is not written for a table.", code="invalid_alert")
    return await expressions.evaluate(
        session,
        access,
        metric.type,
        metric.expression,
        metric.table_name,
        alert.where_sql,
        settings,
    )


# ── Telling people ───────────────────────────────────────────────────────────


def _people(alert: Alert, owner: User) -> list[str]:
    return list(dict.fromkeys([owner.email.lower(), *[r.lower() for r in alert.recipients]]))


async def _tell(
    session: AsyncSession, settings: Settings, alert: Alert, owner: User, subject: str, body: str
) -> tuple[list[str], str]:
    """Email the owner and the extra recipients. Returns who got it, and a note when it could
    not be sent (the event is kept either way, so it shows in the app)."""
    if not await mail_config.is_configured(session, settings):
        return [], "Not emailed: email is not set up on this server."
    people = _people(alert, owner)
    try:
        await mail_config.deliver(session, settings, people, subject, body, [])
    except mailer.MailError as exc:
        await notifications.email_problem(session, str(exc))
        return [], f"Email failed: {exc}"
    return people, ""


def _text(alert: Alert, value: float | None, lead: str) -> str:
    shown = "no value" if value is None else f"{value:g}"
    return (
        f"{lead}\n\n"
        f"Alert: {alert.name}\n"
        f"Condition: goes {WORDS[alert.operator]} {alert.threshold:g}\n"
        f"Value now: {shown}\n"
        f"Checked: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "This alert was set up in Eye of Ender and is checked as its owner."
    )


# ── One check ────────────────────────────────────────────────────────────────


async def _event(
    session: AsyncSession,
    settings: Settings,
    alert: Alert,
    owner: User,
    kind: str,
    value: float | None,
    message: str,
    now: datetime,
) -> None:
    subject, lead = {
        "triggered": (
            f"Alert: {alert.name}",
            f"{describe(alert)}: it is {value:g}." if value is not None else message,
        ),
        "recovered": (
            f"Back to normal: {alert.name}",
            f"{alert.name} is no longer {WORDS[alert.operator]} {alert.threshold:g}.",
        ),
        "error": (f"Alert could not be checked: {alert.name}", message),
    }[kind]
    emailed, note = await _tell(session, settings, alert, owner, subject, _text(alert, value, lead))
    session.add(
        AlertEvent(
            alert_id=alert.id,
            kind=kind,
            value=value,
            message=(message + (" " + note if note else "")).strip()[:500],
            emailed_to=emailed,
            at=now,
        )
    )
    alert.last_notified_at = now
    place = f"/spaces/{alert.space_id}/alerts?alert={alert.id}"
    if kind == "triggered":
        await notifications.notify(
            session,
            [alert.owner_id],
            kind="alert_fired",
            level="warning",
            title=f"{alert.name} went off",
            body=(
                f"It is {value:g}. You asked to know when it {WORDS_OF[alert.operator]} "
                f"{alert.threshold:g}."
            )
            if value is not None
            else message,
            link=place,
        )
    elif kind == "recovered":
        await notifications.notify(
            session,
            [alert.owner_id],
            kind="alert_recovered",
            level="success",
            title=f"{alert.name} is back to normal",
            body=f"It is {value:g} now." if value is not None else "",
            link=place,
        )
    else:
        await notifications.notify(
            session,
            [alert.owner_id],
            kind="alert_error",
            level="warning",
            title=f"{alert.name} can't be checked",
            body=message,
            link=place,
        )


async def _prune_events(session: AsyncSession, alert_id: uuid.UUID) -> None:
    old = list(
        await session.scalars(
            select(AlertEvent.id)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.at.desc())
            .offset(MAX_EVENTS)
        )
    )
    if old:
        await session.execute(delete(AlertEvent).where(AlertEvent.id.in_(old)))


async def _settle(
    session: AsyncSession,
    settings: Settings,
    alert: Alert,
    owner: User,
    value: float | None,
    error: str,
    now: datetime,
) -> None:
    """Record a check, and tell people only when something changed."""
    before = alert.state
    alert.last_checked_at = now
    alert.next_check_at = now + timedelta(minutes=alert.interval_minutes)
    if error:
        alert.state = AlertState.ERROR.value
        alert.last_error = error[:500]
        if before != AlertState.ERROR.value:
            await _event(session, settings, alert, owner, "error", None, error, now)
    elif holds(value, alert.operator, alert.threshold):  # type: ignore[arg-type]
        alert.state = AlertState.TRIGGERED.value
        alert.last_value, alert.last_error = value, ""
        alert.last_triggered_at = now
        again = (
            alert.renotify_hours > 0
            and alert.last_notified_at is not None
            and now - alert.last_notified_at >= timedelta(hours=alert.renotify_hours)
        )
        if before != AlertState.TRIGGERED.value or again:
            await _event(session, settings, alert, owner, "triggered", value, "", now)
    else:
        alert.state = AlertState.OK.value
        alert.last_value, alert.last_error = value, ""
        if before == AlertState.TRIGGERED.value and alert.notify_on_recovery:
            await _event(session, settings, alert, owner, "recovered", value, "", now)
    await _prune_events(session, alert.id)
    await session.commit()


async def check(
    session: AsyncSession, settings: Settings, alert: Alert, now: datetime | None = None
) -> Alert:
    """Look at the number now and act on it. Never raises for a problem with the alert itself."""
    now = now or datetime.now(UTC)
    owner = await session.get(User, alert.owner_id)
    if owner is None or not owner.is_active:
        alert.enabled, alert.next_check_at = False, None
        alert.state, alert.last_error = AlertState.ERROR.value, "The owner can no longer sign in."
        await session.commit()
        return alert
    try:
        access = await spaces.get_access(session, owner, alert.space_id)
    except AppError:
        alert.enabled, alert.next_check_at = False, None
        alert.state = AlertState.ERROR.value
        alert.last_error = "The owner no longer has access to this space."
        await session.commit()
        await notifications.notify(
            session,
            [alert.owner_id],
            kind="alert_off",
            level="warning",
            title=f"{alert.name} was switched off",
            body=alert.last_error,
            link="/alerts",
        )
        return alert
    try:
        value = await current_value(session, access, alert, settings)
    except AppError as exc:
        await _settle(session, settings, alert, owner, None, exc.message, now)
    else:
        await _settle(session, settings, alert, owner, value, "", now)
    return alert


# ── CRUD ─────────────────────────────────────────────────────────────────────


async def _out(session: AsyncSession, alert: Alert) -> AlertOut:
    item = await session.get(DashboardItem, alert.item_id) if alert.item_id else None
    metric = await session.get(SqlExpression, alert.expression_id) if alert.expression_id else None
    return AlertOut.model_validate(alert).model_copy(
        update={
            "item_title": item.title if item else None,
            "expression_name": metric.name if metric else None,
        }
    )


async def list_alerts(session: AsyncSession, access: SpaceAccess, user: User) -> list[AlertOut]:
    found = await session.scalars(
        select(Alert)
        .where(Alert.space_id == access.space.id, Alert.owner_id == user.id)
        .order_by(Alert.created_at, Alert.id)
    )
    return [await _out(session, a) for a in found]


async def get_alert(
    session: AsyncSession, access: SpaceAccess, user: User, alert_id: uuid.UUID
) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None or alert.space_id != access.space.id or alert.owner_id != user.id:
        raise NotFoundError("That alert does not exist.")
    return alert


async def _own_item(
    session: AsyncSession, access: SpaceAccess, user: User, item_id: uuid.UUID
) -> None:
    found = await session.scalar(
        select(DashboardItem.id)
        .join(Dashboard, Dashboard.id == DashboardItem.dashboard_id)
        .where(
            DashboardItem.id == item_id,
            Dashboard.owner_id == user.id,
            Dashboard.space_id == access.space.id,
        )
    )
    if found is None:
        raise NotFoundError("That kept answer does not exist.")


async def create_alert(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    data: AlertCreate,
    settings: Settings,
) -> AlertOut:
    held = await session.scalar(
        select(func.count()).select_from(Alert).where(Alert.owner_id == user.id)
    )
    if held >= settings.alert_max_per_person:
        raise AppError(
            f"You can have at most {settings.alert_max_per_person} alerts.", code="too_many_alerts"
        )
    if data.source_type == "item":
        await _own_item(session, access, user, data.item_id)  # type: ignore[arg-type]
    else:
        metric = await session.get(SqlExpression, data.expression_id)
        if metric is None or metric.space_id != access.space.id:
            raise NotFoundError("That metric does not exist in this space.")
    alert = Alert(
        space_id=access.space.id,
        owner_id=user.id,
        name=data.name,
        source_type=data.source_type,
        item_id=data.item_id if data.source_type == "item" else None,
        value_column=data.value_column if data.source_type == "item" else None,
        expression_id=data.expression_id if data.source_type == "metric" else None,
        where_sql=(data.where_sql or None) if data.source_type == "metric" else None,
        operator=data.operator,
        threshold=data.threshold,
        interval_minutes=data.interval_minutes,
        recipients=reports.check_recipients(list(data.recipients), settings),
        renotify_hours=data.renotify_hours,
        notify_on_recovery=data.notify_on_recovery,
        enabled=data.enabled,
        state=AlertState.NEW.value,
    )
    # A watch that can't read its number is refused now, not discovered at the first check.
    await current_value(session, access, alert, settings)
    session.add(alert)
    await session.commit()
    if alert.enabled:
        await check(session, settings, alert)
    return await _out(session, alert)


async def update_alert(
    session: AsyncSession,
    access: SpaceAccess,
    user: User,
    alert: Alert,
    data: AlertUpdate,
    settings: Settings,
) -> AlertOut:
    changes = data.model_dump(exclude_unset=True, exclude={"recipients"})
    for key, value in changes.items():
        if key in ("where_sql", "value_column"):
            value = value or None
        elif value is None:
            continue
        setattr(alert, key, value)
    if data.recipients is not None:
        alert.recipients = reports.check_recipients(list(data.recipients), settings)
    if alert.enabled:
        await current_value(session, access, alert, settings)  # the edit must still work
        alert.next_check_at = datetime.now(UTC)  # look again soon, with the new condition
    else:
        alert.next_check_at = None
    await session.commit()
    return await _out(session, alert)


async def delete_alert(session: AsyncSession, alert: Alert) -> None:
    await session.delete(alert)
    await session.commit()


async def list_events(session: AsyncSession, alert: Alert, limit: int = 20) -> list[AlertEventOut]:
    events = await session.scalars(
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert.id)
        .order_by(AlertEvent.at.desc())
        .limit(min(limit, MAX_EVENTS))
    )
    return [AlertEventOut.model_validate(e) for e in events]


async def check_now(session: AsyncSession, alert: Alert, settings: Settings) -> AlertOut:
    await check(session, settings, alert)
    return await _out(session, alert)


# ── The scheduler ────────────────────────────────────────────────────────────


async def _check_in_background(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, alert_id: uuid.UUID
) -> None:
    async with sessionmaker() as session:
        alert = await session.get(Alert, alert_id)
        if alert is None or not alert.enabled:
            return
        try:
            await check(session, settings, alert)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Checking alert %s failed", alert_id)


async def run_due(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    tasks: set[asyncio.Task],
    now: datetime | None = None,
) -> int:
    """Start the checks that are due. An alert is claimed by moving its next time forward in one
    UPDATE, so two servers sharing the database never check (and email) the same one twice."""
    now = now or datetime.now(UTC)
    started = 0
    async with sessionmaker() as session:
        due = list(
            await session.execute(
                select(Alert.id, Alert.next_check_at, Alert.interval_minutes)
                .where(Alert.enabled.is_(True), Alert.next_check_at <= now)
                .order_by(Alert.next_check_at)
                .limit(DUE_BATCH)
            )
        )
        for alert_id, was, interval in due:
            claimed = await session.execute(
                update(Alert)
                .where(Alert.id == alert_id, Alert.next_check_at == was)
                .values(next_check_at=now + timedelta(minutes=interval))
            )
            await session.commit()
            if not claimed.rowcount:
                continue
            task = asyncio.create_task(_check_in_background(sessionmaker, settings, alert_id))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            started += 1
    return started
