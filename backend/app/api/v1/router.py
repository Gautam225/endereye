from fastapi import APIRouter

from app.api.v1 import (
    access,
    admin_llm,
    alerts,
    auth,
    benchmarks,
    chat,
    connections,
    dashboards,
    external,
    health,
    knowledge,
    mail,
    metadata,
    monitoring,
    notifications,
    recipients,
    reports,
    sharing,
    spaces,
    users,
)


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(health.router)
    router.include_router(auth.router)
    router.include_router(users.directory_router)  # before /users/{id} routes
    router.include_router(users.router)
    router.include_router(spaces.router)
    router.include_router(metadata.router)
    router.include_router(knowledge.router)
    router.include_router(chat.router)
    router.include_router(sharing.router)
    router.include_router(chat.space_router)
    router.include_router(chat.general_router)
    router.include_router(admin_llm.router)
    router.include_router(monitoring.router)
    router.include_router(connections.router)
    router.include_router(external.router)
    router.include_router(benchmarks.router)
    router.include_router(benchmarks.overview_router)
    router.include_router(dashboards.router)
    router.include_router(reports.router)
    router.include_router(alerts.router)
    router.include_router(mail.router)
    router.include_router(notifications.router)
    router.include_router(recipients.router)
    router.include_router(recipients.status_router)
    router.include_router(access.router)
    return router
