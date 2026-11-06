from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import Settings
from app.db.migrations import expected_revision
from app.db.session import SessionDep
from app.main import create_app
from app.services.health import _describe


def test_error_description_is_one_line_and_never_empty() -> None:
    assert _describe(ValueError("first line\nsecond line")) == "ValueError: first line"
    assert _describe(TimeoutError()) == "TimeoutError"


def test_health_reports_degraded_when_database_is_unreachable(settings: Settings) -> None:
    unreachable = settings.model_copy(
        update={"database_url": SecretStr("postgresql://x:y@127.0.0.1:1/unreachable")}
    )
    with TestClient(create_app(unreachable)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "error"
    assert body["checks"]["pgvector"]["status"] == "error"
    assert body["checks"]["schema"]["status"] == "error"


@pytest.mark.db
def test_health_ok(client: TestClient, migrated_db: None) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["checks"]["database"]["version"].startswith("18")
    assert body["checks"]["pgvector"]["version"]
    assert body["checks"]["pg_trgm"]["version"]
    assert body["checks"]["schema"]["version"] == expected_revision()


@pytest.mark.db
def test_health_says_when_tables_are_out_of_date(
    client: TestClient, migrated_db: None, sql: Callable[..., Any]
) -> None:
    head = expected_revision()
    sql("UPDATE alembic_version SET version_num = '0001'")
    try:
        response = client.get("/api/v1/health")
    finally:
        sql("UPDATE alembic_version SET version_num = :head", {"head": head})

    assert response.status_code == 503
    schema = response.json()["checks"]["schema"]
    assert schema["status"] == "error"
    assert f"the code needs {head}" in schema["detail"]
    assert "alembic upgrade head" in schema["detail"]


@pytest.mark.db
def test_session_dependency_runs_queries(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/test/db")
    async def db_check(session: SessionDep) -> dict[str, str]:
        return {"database": await session.scalar(text("SELECT current_database()"))}

    with TestClient(app) as client:
        assert client.get("/test/db").json() == {"database": settings.sqlalchemy_url.database}
