"""Application factory and ASGI entrypoint.

Run locally:

    uvicorn docqa.main:app --reload

or, without installing the package:

    python -m docqa.cli serve
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI

from docqa.api.errors import register_exception_handlers
from docqa.api.middleware import RequestContextMiddleware
from docqa.api.routes import router
from docqa.core.cache import TTLCache
from docqa.core.config import Settings, get_settings
from docqa.core.logging import configure_logging, get_logger, log_extra
from docqa.core.metrics import Metrics
from docqa.llm.base import LLMClient
from docqa.llm.factory import build_llm_client
from docqa.services.qa_service import QAService

log = get_logger("docqa.app")

DESCRIPTION = """
Production-like document Q&A service.

Send a question and the document text; the service selects the most relevant
excerpts, asks an LLM, post-processes the answer and returns citations.

* `POST /api/v1/qa` — ask a question
* `GET /health` — liveness, cache statistics and counters
* `GET /ready` — readiness probe
"""


def create_app(
    settings: Optional[Settings] = None,
    *,
    llm_client: Optional[LLMClient] = None,
) -> FastAPI:
    """Build the FastAPI application.

    ``llm_client`` is an injection point used by tests to avoid network calls.
    """
    settings = settings or get_settings()
    configure_logging(settings.app_log_level, settings.app_log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = llm_client or build_llm_client(settings)
        cache = (
            TTLCache(
                ttl_seconds=settings.cache_ttl_seconds,
                max_entries=settings.cache_max_entries,
            )
            if settings.cache_enabled
            else None
        )
        service = QAService(settings, client, cache=cache, metrics=Metrics())

        app.state.settings = settings
        app.state.cache = cache
        app.state.qa_service = service
        app.state.started_at = time.monotonic()

        log.info(
            "service_started",
            extra=log_extra(
                event="service_started",
                provider=client.name,
                model=settings.llm_model,
                env=settings.app_env,
            ),
        )
        try:
            yield
        finally:
            await client.aclose()
            log.info("service_stopped", extra=log_extra(event="service_stopped"))

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        RequestContextMiddleware,
        header_name=settings.request_id_header,
        max_body_bytes=settings.app_max_request_bytes,
    )
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
