"""How the PostgreSQL engine turns failures into messages. No database needed."""

from types import SimpleNamespace

import asyncpg
import pytest

from app.engine.duckdb_engine import (
    CancelToken,
    QueryCancelledError,
    QueryFailedError,
    QueryTimeoutError,
)
from app.engine.postgres_engine import DatabaseUnavailableError, failure, type_name


def attribute(name: str) -> asyncpg.Attribute:
    return SimpleNamespace(type=SimpleNamespace(name=name))  # type: ignore[return-value]


@pytest.mark.parametrize(
    ("pg", "ours"),
    [
        ("int4", "INTEGER"),
        ("int8", "BIGINT"),
        ("numeric", "DECIMAL"),
        ("float8", "DOUBLE"),
        ("text", "VARCHAR"),
        ("timestamptz", "TIMESTAMP WITH TIME ZONE"),
        ("interval", "INTERVAL"),
        ("jsonb", "JSON"),
        ("int4[]", "INTEGER[]"),
        ("point", "POINT"),
    ],
)
def test_column_types_use_the_names_the_rest_of_the_app_understands(pg: str, ours: str) -> None:
    assert type_name(attribute(pg)) == ours


def test_a_query_that_runs_too_long_is_a_timeout() -> None:
    error = failure(
        asyncpg.QueryCanceledError("canceling statement due to statement timeout"), None, 30
    )

    assert isinstance(error, QueryTimeoutError) and "30 seconds" in error.message


def test_pressing_stop_is_a_cancel_not_a_failure() -> None:
    token = CancelToken()
    token.cancel()

    assert isinstance(failure(asyncpg.QueryCanceledError("x"), token, 30), QueryCancelledError)
    assert isinstance(
        failure(asyncpg.ConnectionDoesNotExistError("closed"), token, 30), QueryCancelledError
    )


def test_a_mistake_in_the_query_keeps_the_databases_short_message_so_it_can_be_corrected() -> None:
    error = failure(asyncpg.UndefinedColumnError('column "revenue" does not exist'), None, 30)

    assert isinstance(error, QueryFailedError)
    assert 'column "revenue" does not exist' in error.message
    assert isinstance(
        failure(asyncpg.DivisionByZeroError("division by zero"), None, 30), QueryFailedError
    )


def test_the_message_is_cut_to_a_short_length() -> None:
    error = failure(asyncpg.UndefinedTableError("relation " + "x" * 5000), None, 30)

    assert len(error.message) < 300


@pytest.mark.parametrize(
    "exc",
    [
        asyncpg.InsufficientPrivilegeError(
            'permission denied for table "salaries" on host 10.0.0.5'
        ),
        asyncpg.ReadOnlySQLTransactionError("cannot execute DELETE in a read-only transaction"),
        asyncpg.DiskFullError("could not write to /var/lib/postgresql/16/main/base/123"),
        asyncpg.AdminShutdownError("terminating connection at 10.0.0.5"),
        RuntimeError("secret internals"),
    ],
)
def test_problems_with_the_server_or_the_login_get_fixed_messages_without_details(
    exc: BaseException,
) -> None:
    error = failure(exc, None, 30)

    for leaked in ("salaries", "10.0.0.5", "/var/lib", "secret internals", "DELETE"):
        assert leaked not in error.message


def test_a_lost_connection_is_reported_as_unavailable() -> None:
    assert isinstance(
        failure(OSError("connection reset by 10.0.0.5"), None, 30), DatabaseUnavailableError
    )
    assert isinstance(failure(asyncpg.InterfaceError("closed"), None, 30), DatabaseUnavailableError)
