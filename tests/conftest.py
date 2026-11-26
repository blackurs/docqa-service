"""Shared test fixtures and helpers."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from docqa.core.config import Settings
from docqa.core.errors import AppError
from docqa.llm.base import LLMRequest, LLMResponse
from docqa.main import create_app

SAMPLE_QUESTION = "Сколько секунд таймаут по умолчанию и сколько повторных попыток?"

SAMPLE_CONTEXT = (
    "Сервис обработки документов использует таймаут 20 секунд по умолчанию. "
    "Значение настраивается переменной LLM_TIMEOUT_SECONDS. "
    "При сетевой ошибке клиент выполняет до двух повторных попыток. "
    "Результаты успешных ответов кешируются на 300 секунд. "
    "Ответы, полученные через fallback, в кеш не сохраняются."
)


class FakeClock:
    """Monotonic clock under test control."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class StubLLMClient:
    """Configurable no-network LLM client that counts calls."""

    def __init__(
        self,
        text: str = "Таймаут составляет 20 секунд. Повторных попыток — две.",
        error: Optional[AppError] = None,
    ) -> None:
        self.name = "stub"
        self.text = text
        self.error = error
        self.calls = 0
        self.requests: List[LLMRequest] = []
        self.closed = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            text=self.text,
            model="stub-model",
            provider=self.name,
            prompt_tokens=11,
            completion_tokens=5,
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's shell environment from leaking into tests."""
    for name in (
        "APP_ENV",
        "APP_LOG_LEVEL",
        "APP_LOG_FORMAT",
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_RETRY_BACKOFF_SECONDS",
        "CACHE_ENABLED",
        "CACHE_TTL_SECONDS",
        "FALLBACK_ENABLED",
        "MOCK_FAIL_MODE",
        "MAX_QUESTION_CHARS",
        "MAX_CONTEXT_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        llm_provider="mock",
        cache_enabled=True,
        cache_ttl_seconds=60,
        _env_file=None,
    )


@pytest.fixture
def stub_client() -> StubLLMClient:
    return StubLLMClient()


@pytest.fixture
def make_app(settings: Settings) -> Callable[..., Any]:
    def factory(client: Any = None, **overrides: Any) -> Any:
        effective = settings.model_copy(update=overrides) if overrides else settings
        return create_app(effective, llm_client=client)

    return factory


@pytest.fixture
def api_client(make_app: Callable[..., Any], stub_client: StubLLMClient) -> Any:
    app = make_app(stub_client)
    with TestClient(app) as client:
        yield client


def make_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"question": SAMPLE_QUESTION, "context": SAMPLE_CONTEXT}
    payload.update(overrides)
    return payload
