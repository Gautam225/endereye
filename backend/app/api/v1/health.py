from fastapi import APIRouter, Request, Response

from app import __version__
from app.core.config import Settings
from app.schemas.health import HealthResponse
from app.services.health import check_database

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is not ready"}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    """App status plus PostgreSQL, pgvector, and pg_trgm checks. Returns 503 if any fail."""
    settings: Settings = request.app.state.settings
    checks = await check_database(request.app.state.engine, show_errors=not settings.is_production)
    healthy = all(check.status == "ok" for check in checks.values())
    if not healthy:
        response.status_code = 503
    return HealthResponse(
        status="ok" if healthy else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        checks=checks,
    )
