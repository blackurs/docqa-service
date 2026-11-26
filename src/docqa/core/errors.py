"""Domain error hierarchy.

Every error carries a stable machine-readable ``code``, an HTTP status for the
API layer and an optional list of human-friendly ``details``. This keeps the
API error contract consistent across layers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class AppError(Exception):
    """Base class for all expected (handled) application errors."""

    code: str = "internal_error"
    http_status: int = 500
    default_message: str = "Internal server error"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        details: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: List[Dict[str, Any]] = details or []
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class InvalidInputError(AppError):
    """Request payload violates business validation rules."""

    code = "validation_error"
    http_status = 422
    default_message = "Invalid input payload"


class LLMError(AppError):
    """Base class for failures of the external LLM call."""

    code = "llm_error"
    http_status = 502
    default_message = "LLM request failed"


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    http_status = 504
    default_message = "LLM request timed out"


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"
    http_status = 503
    default_message = "LLM provider is unavailable"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    http_status = 429
    default_message = "LLM provider rate limit exceeded"


class LLMBadResponseError(LLMError):
    code = "llm_bad_response"
    http_status = 502
    default_message = "LLM provider returned an invalid response"


class PostprocessingError(AppError):
    """The model answered, but the answer cannot be used as-is."""

    code = "postprocessing_error"
    http_status = 502
    default_message = "LLM answer failed post-processing"


class ConfigurationError(AppError):
    code = "configuration_error"
    http_status = 500
    default_message = "Service is misconfigured"
