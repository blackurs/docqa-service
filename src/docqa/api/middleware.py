"""HTTP middleware: request correlation id, body size guard and access logs."""

from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from docqa.core.logging import get_logger, log_extra, request_id_ctx

log = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id to logs and responses, enforce a request size limit."""

    def __init__(
        self,
        app,
        *,
        header_name: str = "X-Request-ID",
        max_body_bytes: int = 262_144,
    ) -> None:
        super().__init__(app)
        self._header_name = header_name
        self._max_body_bytes = max_body_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(self._header_name) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            declared_size = request.headers.get("content-length")
            if request.method in {"POST", "PUT", "PATCH"} and declared_size:
                try:
                    too_large = int(declared_size) > self._max_body_bytes
                except ValueError:
                    too_large = False
                if too_large:
                    log.warning(
                        "request_too_large",
                        extra=log_extra(
                            event="request_too_large",
                            status_code=413,
                            path=request.url.path,
                        ),
                    )
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": (f"Request body exceeds {self._max_body_bytes} bytes"),
                                "request_id": request_id,
                            }
                        },
                    )
                    response.headers[self._header_name] = request_id
                    return response

            log.debug(
                "request_started",
                extra=log_extra(
                    event="request_started", method=request.method, path=request.url.path
                ),
            )
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)

        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        response.headers[self._header_name] = request_id
        log_fn = log.debug if request.url.path in {"/health", "/ready", "/"} else log.info
        log_fn(
            "request_completed",
            extra=log_extra(
                event="request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            ),
        )
        return response
