"""Structured logging.

Logs are emitted as one JSON object per line (``APP_LOG_FORMAT=json``) which is
friendly to Docker, Loki, CloudWatch, etc. ``APP_LOG_FORMAT=text`` gives a more
readable local format.

A ``request_id`` context variable is propagated automatically, so every log
record produced while handling a request can be correlated with the response
header ``X-Request-ID``.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# Fields copied from ``record`` into the JSON payload when present.
_EXTRA_FIELDS = (
    "event",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "cache",
    "provider",
    "model",
    "error_code",
    "question_chars",
    "context_chars",
    "excerpts",
    "attempt",
    "degraded",
)

_CONFIGURED = False


class RequestIdFilter(logging.Filter):
    """Ensure every record has a ``request_id`` attribute."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", ""):
            record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "")
        if request_id:
            payload["request_id"] = request_id
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human readable single-line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", "")
        base = super().format(record)
        return f"{base} [request_id={rid or '-'}]"


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure the root logger once per process."""
    global _CONFIGURED  # noqa: PLW0603 - simple process-wide flag
    root = logging.getLogger()
    root.setLevel(level.upper())

    if _CONFIGURED:
        for handler in root.handlers:
            handler.setLevel(level.upper())
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level.upper())
    handler.addFilter(RequestIdFilter())
    if fmt == "text":
        handler.setFormatter(
            TextFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    else:
        handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)
    _CONFIGURED = True

    # Access logs duplicate our request_completed events.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(**kwargs: Any) -> Dict[str, Any]:
    """Helper to build an ``extra=`` dict, skipping ``None`` values."""
    return {key: value for key, value in kwargs.items() if value is not None}


def set_request_id(request_id: Optional[str]) -> None:
    request_id_ctx.set(request_id or "")
