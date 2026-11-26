"""FastAPI dependencies (thin accessors over ``app.state``)."""

from __future__ import annotations

from fastapi import Request

from docqa.core.config import Settings
from docqa.core.errors import ConfigurationError
from docqa.services.qa_service import QAService


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise ConfigurationError("Application settings are not initialized")
    return settings


def get_qa_service(request: Request) -> QAService:
    service = getattr(request.app.state, "qa_service", None)
    if service is None:
        raise ConfigurationError("Q&A service is not initialized")
    return service
