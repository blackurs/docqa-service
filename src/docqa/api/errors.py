"""Exception handlers: a single, predictable error envelope for the API."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from docqa.core.errors import AppError
from docqa.core.logging import get_logger, log_extra

log = get_logger(__name__)


def _error_payload(
    code: str,
    message: str,
    request_id: str,
    details: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    if request_id:
        error["request_id"] = request_id
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        log.warning(
            "app_error",
            extra=log_extra(
                event="app_error",
                error_code=exc.code,
                status_code=exc.http_status,
                path=request.url.path,
            ),
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_payload(exc.code, exc.message, request_id, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "reason": error.get("msg", "invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        log.info(
            "request_validation_failed",
            extra=log_extra(
                event="request_validation_failed",
                error_code="validation_error",
                status_code=422,
                path=request.url.path,
            ),
        )
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "validation_error", "Request payload failed validation", request_id, details
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        log.exception(
            "unhandled_error",
            extra=log_extra(
                event="unhandled_error",
                error_code="internal_error",
                status_code=500,
                path=request.url.path,
            ),
        )
        del exc  # details stay in the server log, never in the response
        return JSONResponse(
            status_code=500,
            content=_error_payload("internal_error", "Internal server error", request_id),
        )
