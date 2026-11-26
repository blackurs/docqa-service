"""HTTP request/response schemas (the public API contract)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QARequest(BaseModel):
    """Question about a document provided inline."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "question": "Какой таймаут по умолчанию у LLM-клиента?",
                    "context": (
                        "Сервис использует таймаут 20 секунд по умолчанию. "
                        "Значение настраивается переменной LLM_TIMEOUT_SECONDS. "
                        "При таймауте выполняется до двух повторных попыток."
                    ),
                    "top_k": 3,
                    "allow_fallback": True,
                }
            ]
        },
    )

    # Absolute safety caps. Business limits (MIN/MAX_QUESTION_CHARS,
    # MAX_CONTEXT_CHARS) come from configuration and are enforced by the
    # service layer, keeping limits out of hardcoded business logic.
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User question, 1..2000 characters (configurable business limit applies).",
    )
    context: str = Field(
        ...,
        min_length=20,
        max_length=100_000,
        description="Source document text (configurable business limit applies).",
    )
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="How many context excerpts to use. Defaults to TOP_K_EXCERPTS.",
    )
    allow_fallback: bool = Field(
        default=True,
        description="Return an extractive answer if the LLM is unavailable instead of an error.",
    )

    @field_validator("question", "context")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class CitationModel(BaseModel):
    index: int = Field(..., description="1-based excerpt number used in the prompt.")
    text: str = Field(..., description="Excerpt text.")
    score: float = Field(..., description="Relevance score of the excerpt.")


class UsageModel(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class QAResponse(BaseModel):
    request_id: str
    answer: str
    citations: List[CitationModel]
    degraded: bool = Field(
        ..., description="True when the answer was produced without the LLM (fallback)."
    )
    degradation_reason: Optional[str] = Field(
        None, description="Error code that triggered the fallback, if any."
    )
    cached: bool
    provider: str
    model: str
    latency_ms: float
    usage: UsageModel


class CacheStatsModel(BaseModel):
    size: int
    max_entries: int
    ttl_seconds: float
    hits: int
    misses: int
    hit_rate: float
    expired: int
    evictions: int


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    env: str
    provider: str
    model: str
    uptime_seconds: float
    cache: Optional[CacheStatsModel] = None
    counters: Dict[str, Any] = Field(default_factory=dict)


class ReadinessResponse(BaseModel):
    status: str
    checks: Dict[str, str]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: List[Dict[str, Any]] = Field(default_factory=list)
    request_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorBody
