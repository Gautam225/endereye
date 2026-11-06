"""The one loop that looks, every few seconds, for reports and alerts that are due. What is due
is claimed in the database, so several servers can run it without doing anything twice."""

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services import alerts, notifications, reports

logger = logging.getLogger(__name__)


async def scheduler_loop(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, tasks: set[asyncio.Task]
) -> None:
    last_prune = 0.0
    while True:
        for name, run_due in (("reports", reports.run_due), ("alerts", alerts.run_due)):
            try:
                await run_due(sessionmaker, settings, tasks)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Looking for due %s failed", name)
        if time.monotonic() - last_prune > 3600:  # old notifications are forgotten once an hour
            last_prune = time.monotonic()
            try:
                await notifications.prune(sessionmaker)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Forgetting old notifications failed")
        await asyncio.sleep(settings.report_poll_seconds)
