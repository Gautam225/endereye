"""A broken database must produce a clear 503 that says how to fix it, not a generic 500."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.config import Settings
from app.db.errors import find_database_problem
from app.main import create_app


class DriverError(Exception):
    """Stands in for asyncpg's error, which carries the PostgreSQL error code."""

    def __init__(self, message: str, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("message", "sqlstate", "kind"),
    [
        ('password authentication failed for user "Servers"', "28P01", "unavailable"),
        ('database "nope" does not exist', "3D000", "unavailable"),
        ("the database system is starting up", "57P03", "unavailable"),
        ('relation "users" does not exist', "42P01", "not_ready"),
        ('column "replaced_by_id" does not exist', "42703", "not_ready"),
    ],
)
def test_postgres_error_codes_are_recognised(
    settings: Settings, message: str, sqlstate: str, kind: str
) -> None:
    wrapper = ProgrammingError if kind == "not_ready" else DBAPIError
    error = wrapper("SELECT 1", {}, DriverError(message, sqlstate))

    problem = find_database_problem(error, settings)

    assert problem is not None
    assert (problem.kind, problem.reason) == (kind, f"{message}.")


def test_unrelated_errors_are_not_mistaken_for_database_problems(settings: Settings) -> None:
    assert find_database_problem(ValueError("bad value"), settings) is None
    assert (
        find_database_problem(DBAPIError("SELECT 1", {}, DriverError("dup", "23505")), settings)
        is None
    )
    # An OSError that didn't come from the database driver (e.g. a file problem).
    try:
        open("C:/definitely/not/here.txt")  # noqa: SIM115
    except OSError as error:
        assert find_database_problem(error, settings) is None


def _unreachable(settings: Settings, env: str = "test") -> Settings:
    return settings.model_copy(
        update={
            "database_url": SecretStr("postgresql://x:y@127.0.0.1:1/unreachable"),
            "app_env": env,
        }
    )


def test_unreachable_database_gives_a_clear_503(settings: Settings) -> None:
    with TestClient(create_app(_unreachable(settings))) as client:
        responses = [
            client.get("/api/v1/auth/setup"),
            client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x"}),
        ]

    for response in responses:
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "database_unavailable"
        assert "127.0.0.1:1" in error["details"]["reason"]
        assert "setup_database.py" in error["message"]
        assert response.headers["Retry-After"] == "5"


def test_production_does_not_reveal_database_details(settings: Settings) -> None:
    with TestClient(create_app(_unreachable(settings, env="production"))) as client:
        response = client.get("/api/v1/auth/setup")

    error = response.json()["error"]
    assert (response.status_code, error["code"]) == (503, "database_unavailable")
    assert "details" not in error
    assert "127.0.0.1" not in response.text and "setup_database" not in response.text
