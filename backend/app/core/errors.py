"""Error types and handlers. Every error response has the same JSON shape:

    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": ...}}

`details` is only present when there is something useful to add.
"""

import logging
import math
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.middleware import REQUEST_ID_HEADER

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An expected error raised by our own code; the message is shown to the user."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        details: Any = None,
        status_code: int | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class UnauthorizedError(AppError):
    """Not signed in, or the session is no longer valid (401)."""

    status_code = 401
    code = "not_authenticated"

    def __init__(self, message: str = "Please sign in.", *, code: str | None = None) -> None:
        super().__init__(message, code=code, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"

    def __init__(self, message: str, *, retry_after: float) -> None:
        seconds = max(1, math.ceil(retry_after))
        super().__init__(
            message, details={"retry_after": seconds}, headers={"Retry-After": str(seconds)}
        )


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    response_headers = dict(headers or {})
    if request_id:
        # The 500 handler runs outside the request middleware, so set the header here too.
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse({"error": body}, status_code=status_code, headers=response_headers)


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return f"HTTP {status_code}"


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    phrase = _status_phrase(exc.status_code)
    code = phrase.lower().replace(" ", "_").replace("-", "_")
    if isinstance(exc.detail, str):
        message, details = exc.detail, None
    else:
        message, details = phrase, exc.detail
    return error_response(request, exc.status_code, code, message, details, exc.headers)


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Only field, message and type: the raw input is left out because it may contain secrets.
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return error_response(request, 422, "validation_error", "The request is not valid.", details)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
        extra={"request_id": getattr(request.state, "request_id", None)},
    )
    return error_response(
        request, 500, "internal_error", "Something went wrong on our side. Please try again."
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
