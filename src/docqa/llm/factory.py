"""Provider factory: single place that maps configuration to an implementation."""

from __future__ import annotations

from docqa.core.config import Settings
from docqa.core.errors import ConfigurationError
from docqa.llm.base import LLMClient
from docqa.llm.providers.mock import MockLLMClient
from docqa.llm.providers.openai_compat import OpenAIChatClient


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "mock":
        return MockLLMClient(
            latency_ms=settings.mock_latency_ms,
            fail_mode=settings.mock_fail_mode,
        )
    if settings.llm_provider == "openai":
        if not settings.api_key:
            raise ConfigurationError("LLM_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAIChatClient(settings)
    raise ConfigurationError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")
