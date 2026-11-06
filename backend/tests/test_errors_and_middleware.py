import json
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import JsonFormatter, RequestIdFilter, request_id_var
from app.main import create_app


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/test/app-error")
    async def app_error() -> None:
        raise AppError(
            "This space is archived.", status_code=409, code="space_archived", details={"id": 7}
        )

    @app.get("/test/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    return app


@pytest.fixture
def test_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_unknown_route_returns_json_404(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_app_error_keeps_its_status_code_and_details(test_client: TestClient) -> None:
    response = test_client.get("/test/app-error")
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "space_archived",
        "message": "This space is archived.",
        "request_id": response.headers["X-Request-ID"],
        "details": {"id": 7},
    }


def test_validation_error_lists_fields_without_echoing_input(test_client: TestClient) -> None:
    response = test_client.get("/test/items/not-a-number")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "path.item_id"
    assert "not-a-number" not in response.text


def test_unexpected_error_is_logged_but_not_leaked(
    test_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = test_client.get("/test/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "secret internal detail" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]

    logged = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert logged, "the traceback should be logged"
    assert logged[0].request_id == error["request_id"]


def test_request_id_is_generated(test_client: TestClient) -> None:
    request_id = test_client.get("/api/v1/does-not-exist").headers["X-Request-ID"]
    assert len(request_id) == 32


def test_valid_incoming_request_id_is_reused(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/nope", headers={"X-Request-ID": "trace-abc.123"})
    assert response.headers["X-Request-ID"] == "trace-abc.123"


def test_invalid_incoming_request_id_is_replaced(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/nope", headers={"X-Request-ID": "bad id <script>"})
    assert response.headers["X-Request-ID"] != "bad id <script>"
    assert len(response.headers["X-Request-ID"]) == 32


def test_cors_allows_only_configured_origins(test_client: TestClient, settings: Settings) -> None:
    allowed = settings.cors_origins[0]
    preflight = {"Access-Control-Request-Method": "GET"}

    ok = test_client.options("/api/v1/health", headers={"Origin": allowed, **preflight})
    assert ok.headers.get("access-control-allow-origin") == allowed

    blocked = test_client.options(
        "/api/v1/health", headers={"Origin": "https://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in blocked.headers


def test_json_log_lines_carry_request_id_and_extras() -> None:
    record = logging.getLogger("app.test").makeRecord(
        "app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None, extra={"rows": 3}
    )
    token = request_id_var.set("req-1")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "hello world"
    assert line["request_id"] == "req-1"
    assert line["rows"] == 3
