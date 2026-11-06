"""FastAPI application. Run from the backend folder:  uvicorn app.main:app --reload"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import build_api_router
from app.core.config import ConfigError, Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
)
from app.core.rate_limit import SlidingWindowLimiter
from app.db.errors import register_database_error_handlers
from app.db.session import create_engine, create_sessionmaker
from app.engine import duckdb_engine
from app.llm.gateway import LLMGateway
from app.llm.recorder import CallRecorder
from app.services import benchmarks as benchmark_service
from app.services import knowledge as knowledge_service
from app.services import reports as report_service
from app.services import scheduler as scheduling
from app.services.auth import LoginLimits
from app.services.health import check_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    # Report database status at startup, but don't block it: /api/v1/health keeps reporting.
    checks = await check_database(engine, show_errors=True)
    problems = {name: check.detail for name, check in checks.items() if check.status != "ok"}
    if problems:
        only_tables = set(problems) == {"schema"}
        fix = (
            "alembic upgrade head"
            if only_tables
            else "python scripts/setup_database.py (it sets up the login, databases, and tables)"
        )
        logger.warning(
            "Database not ready - sign-in won't work until it is fixed. In the backend folder "
            "run: %s, then restart the backend.",
            fix,
            extra=problems,
        )
    else:
        logger.info(
            "Database ready",
            extra={"postgres": checks["database"].version, "pgvector": checks["pgvector"].version},
        )

    # Benchmark runs are background tasks. One that a restart cut short can never finish.
    app.state.benchmark_tasks = set()
    # Chat answers run as background tasks too, so a refreshed page can rejoin them.
    app.state.chat_tasks = set()
    # Documents are read and indexed in the background after the upload is saved.
    app.state.index_tasks = set()
    # Scheduled reports: runs are background tasks, and one loop starts the ones that are due.
    app.state.report_tasks = set()
    try:
        lost_reports = await report_service.fail_interrupted_runs(app.state.sessionmaker)
        if lost_reports:
            logger.warning("Marked %d interrupted report run(s) as failed", lost_reports)
    except Exception:
        logger.debug("Could not check for interrupted report runs", exc_info=True)
    scheduler = (
        asyncio.create_task(
            scheduling.scheduler_loop(app.state.sessionmaker, settings, app.state.report_tasks)
        )
        if settings.report_scheduler
        else None
    )
    try:
        lost = await knowledge_service.fail_interrupted_documents(app.state.sessionmaker)
        if lost:
            logger.warning("Marked %d interrupted document(s) as failed", lost)
    except Exception:
        logger.debug("Could not check for interrupted documents", exc_info=True)
    try:
        interrupted = await benchmark_service.fail_interrupted_runs(app.state.sessionmaker)
        if interrupted:
            logger.warning("Marked %d interrupted benchmark run(s) as failed", interrupted)
    except Exception:
        logger.debug("Could not check for interrupted benchmark runs", exc_info=True)

    recorder = CallRecorder(app.state.sessionmaker)
    llm = LLMGateway.from_settings(settings, recorder=recorder)
    app.state.llm = llm
    key_counts = {provider.name: len(provider.pool.keys) for provider in llm.providers}
    if llm.configured:
        logger.info("LLM keys loaded", extra=key_counts)
    else:
        logger.warning("No LLM keys configured - add OPENROUTER_API_KEY_1 / GROQ_API_KEY_1 to .env")
    # Check model ids in the background so startup never waits on the network.
    model_check = asyncio.create_task(llm.check_models())

    # Folder for uploaded data, and DuckDB's Delta/Excel extensions (downloaded once).
    settings.data_path.mkdir(parents=True, exist_ok=True)
    extensions = asyncio.create_task(asyncio.to_thread(duckdb_engine.install_extensions))

    try:
        yield
    finally:
        for task in list(app.state.benchmark_tasks):
            task.cancel()
        if app.state.benchmark_tasks:
            await asyncio.gather(*app.state.benchmark_tasks, return_exceptions=True)
        if scheduler is not None:
            scheduler.cancel()
        background = app.state.chat_tasks | app.state.index_tasks | app.state.report_tasks
        if scheduler is not None:
            background.add(scheduler)
        for task in list(background):
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        model_check.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await model_check
        with contextlib.suppress(Exception):
            await extensions
        await llm.aclose()
        await recorder.aclose()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(json_logs=settings.is_production, debug=settings.app_debug)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        # API docs only outside production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    register_error_handlers(app)
    register_database_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Uploads may be up to MAX_UPLOAD_MB; one extra MB covers the form fields around the file.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=(settings.max_upload_mb + 1) * 1024**2)
    # Added last = outermost, so every response (CORS preflights too) gets a request ID.
    app.add_middleware(RequestContextMiddleware)
    app.state.login_limits = LoginLimits.default()
    # "Forgot password" emails: few per address, so nobody can use it to flood an inbox.
    app.state.reset_limits = LoginLimits(
        SlidingWindowLimiter(3, 15 * 60), SlidingWindowLimiter(15, 15 * 60)
    )
    app.include_router(build_api_router())
    return app


try:
    app = create_app()
except ConfigError as exc:
    raise SystemExit(f"\n[Eye of Ender] Cannot start.\n{exc}\n") from None
