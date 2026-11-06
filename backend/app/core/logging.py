"""Logging setup: one stdout handler, a request ID on every line, JSON in production."""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has. Anything else came in through `extra=` and is logged as a field.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "request_id",
    "color_message",  # Uvicorn's ANSI-colored copy of the message
}


def _extra_fields(record: logging.LogRecord) -> dict[str, object]:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}


_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^:/@\s]*):[^@\s]+@", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"(?P<name>\b(?:password|passwd|pwd|secret|token|api[_-]?key)\b[\"']?)(?P<sep>\s*[=:]\s*)"
    r"(?:'[^']*'|\"[^\"]*\"|[^\s,;&}]+)",
    re.I,
)
_SECRET_FIELD = re.compile(r"password|passwd|secret|token|api_?key", re.I)


def redact(text: str) -> str:
    """Hides passwords written into a log line: in a URL (user:password@host) or as password=...
    Nothing here logs a password on purpose; this is the net for the day something does."""
    text = _URL_CREDENTIALS.sub(r"\g<scheme>\g<user>:***@", text)
    return _SECRET_ASSIGNMENT.sub(r"\g<name>\g<sep>***", text)


class RedactFilter(logging.Filter):
    """Redacts the message, and any `extra=` field that is a string or has a secret-like name."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, ()
        for key, value in _extra_fields(record).items():
            if _SECRET_FIELD.search(key):
                setattr(record, key, "***")
            elif isinstance(value, str):
                setattr(record, key, redact(value))
        return True


class RequestIdFilter(logging.Filter):
    """Adds the current request ID to records that don't already carry one."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def formatException(self, ei) -> str:
        return redact(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line format for local development."""

    def formatException(self, ei) -> str:
        return redact(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            f"{record.levelname:<7}",
            record.name,
        ]
        request_id = getattr(record, "request_id", None)
        if request_id:
            parts.append(f"[{request_id[:8]}]")
        parts.append(record.getMessage())
        parts.extend(f"{k}={v}" for k, v in _extra_fields(record).items())
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(*, json_logs: bool, debug: bool) -> None:
    """Route all logs (ours and Uvicorn's) through one stdout handler. Safe to call repeatedly."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_eye_of_ender", False)]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else ConsoleFormatter())
    handler.addFilter(RequestIdFilter())
    handler.addFilter(RedactFilter())
    handler._eye_of_ender = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("app").setLevel(logging.DEBUG if debug else logging.INFO)

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # Our RequestContextMiddleware writes the access log (with request IDs) instead.
    logging.getLogger("uvicorn.access").disabled = True
    # The app only reads migration info (health check); alembic's plugin chatter is noise here.
    logging.getLogger("alembic").setLevel(logging.WARNING)
