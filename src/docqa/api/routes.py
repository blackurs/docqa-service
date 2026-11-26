"""HTTP routes.

Thin layer only: parse -> delegate to :class:`QAService` -> map to response.
No prompt building or provider logic lives here.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, Response, status

from docqa.api.deps import get_app_settings, get_qa_service
from docqa.api.schemas import (
    CitationModel,
    ErrorResponse,
    HealthResponse,
    QARequest,
    QAResponse,
    ReadinessResponse,
    UsageModel,
)
from docqa.core.config import Settings
from docqa.services.qa_service import QAResult, QAService

router = APIRouter()

_ERROR_RESPONSES = {
    422: {"model": ErrorResponse, "description": "Validation error"},
    429: {"model": ErrorResponse, "description": "LLM rate limit exceeded"},
    502: {"model": ErrorResponse, "description": "LLM returned an invalid response"},
    503: {"model": ErrorResponse, "description": "LLM unavailable and fallback disabled"},
    504: {"model": ErrorResponse, "description": "LLM request timed out"},
}


@router.get("/", include_in_schema=False)
async def root(request: Request) -> dict:
    return {
        "service": "docqa-service",
        "docs": str(request.url_for("swagger_ui_html")),
        "openapi": str(request.url_for("openapi")),
        "health": str(request.url_for("health")),
        "endpoint": "POST /api/v1/qa",
    }


@router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    service: QAService = Depends(get_qa_service),
) -> HealthResponse:
    uptime = round(time.monotonic() - getattr(request.app.state, "started_at", time.monotonic()), 3)
    cache_stats = None
    cache = getattr(request.app.state, "cache", None)
    if cache is not None:
        cache_stats = cache.stats()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        env=settings.app_env,
        provider=settings.llm_provider,
        model=settings.llm_model,
        uptime_seconds=uptime,
        cache=cache_stats,
        counters=service.metrics.snapshot(),
    )


@router.get("/ready", response_model=ReadinessResponse, tags=["ops"])
async def ready(settings: Settings = Depends(get_app_settings)) -> ReadinessResponse:
    provider_ready = settings.llm_provider == "mock" or bool(settings.api_key)
    return ReadinessResponse(
        status="ready" if provider_ready else "not_ready",
        checks={
            "config": "ok",
            "provider": "ok" if provider_ready else "missing_api_key",
        },
    )


def _to_response(result: QAResult, request_id: str) -> QAResponse:
    return QAResponse(
        request_id=request_id,
        answer=result.answer,
        citations=[
            CitationModel(index=citation.index, text=citation.text, score=citation.score)
            for citation in result.citations
        ],
        degraded=result.degraded,
        degradation_reason=result.degradation_reason,
        cached=result.cached,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        usage=UsageModel(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        ),
    )


@router.post(
    "/api/v1/qa",
    response_model=QAResponse,
    status_code=status.HTTP_200_OK,
    responses=_ERROR_RESPONSES,
    tags=["qa"],
    summary="Answer a question about the supplied document",
)
async def ask(
    payload: QARequest,
    request: Request,
    response: Response,
    service: QAService = Depends(get_qa_service),
) -> QAResponse:
    result = await service.answer(
        question=payload.question,
        context=payload.context,
        top_k=payload.top_k,
        allow_fallback=payload.allow_fallback,
    )
    request_id: str = getattr(request.state, "request_id", "")

    response.headers["X-Cache"] = "HIT" if result.cached else "MISS"
    if result.degraded:
        response.headers["X-Degraded"] = "true"
        response.headers["X-Degradation-Reason"] = result.degradation_reason or "unknown"

    return _to_response(result, request_id)
