from __future__ import annotations

import pytest

from conftest import SAMPLE_CONTEXT, SAMPLE_QUESTION, FakeClock, StubLLMClient
from docqa.core.cache import TTLCache
from docqa.core.config import Settings
from docqa.core.errors import (
    InvalidInputError,
    LLMUnavailableError,
    PostprocessingError,
)
from docqa.core.metrics import Metrics
from docqa.services.qa_service import QAService


def make_settings(**overrides: object) -> Settings:
    values = {
        "app_env": "test",
        "llm_provider": "mock",
        "cache_enabled": True,
        "cache_ttl_seconds": 10,
        "max_question_chars": 500,
        "max_context_chars": 20_000,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


async def test_cache_hit_skips_llm(tmp_path) -> None:
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    client = StubLLMClient()
    service = QAService(make_settings(), client, cache=cache, clock=clock)

    first = await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)
    second = await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    assert first.cached is False
    assert second.cached is True
    assert second.answer == first.answer
    assert client.calls == 1


async def test_cache_expires_after_ttl() -> None:
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    client = StubLLMClient()
    service = QAService(make_settings(), client, cache=cache, clock=clock)

    await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)
    clock.advance(11)
    result = await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    assert result.cached is False
    assert client.calls == 2


async def test_fallback_is_not_cached() -> None:
    clock = FakeClock()
    cache = TTLCache(ttl_seconds=10, clock=clock)
    failing = StubLLMClient(error=LLMUnavailableError("down"))
    broken_service = QAService(make_settings(), failing, cache=cache, clock=clock)

    degraded = await broken_service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)
    assert degraded.degraded is True

    healthy = StubLLMClient()
    healthy_service = QAService(make_settings(), healthy, cache=cache, clock=clock)
    recovered = await healthy_service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    assert recovered.cached is False
    assert recovered.degraded is False
    assert healthy.calls == 1


async def test_strict_mode_raises_when_llm_is_down() -> None:
    client = StubLLMClient(error=LLMUnavailableError("down"))
    service = QAService(make_settings(), client)

    with pytest.raises(LLMUnavailableError):
        await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT, allow_fallback=False)


async def test_postprocessing_failure_triggers_fallback() -> None:
    client = StubLLMClient(text="   ")
    service = QAService(make_settings(), client)

    result = await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    assert result.degraded is True
    assert result.degradation_reason == PostprocessingError.code
    assert result.answer


@pytest.mark.parametrize(
    "question",
    ["", "   ", "да", "а" * 600],
)
async def test_invalid_questions_raise(question: str) -> None:
    service = QAService(make_settings(), StubLLMClient())
    with pytest.raises(InvalidInputError):
        await service.answer(question, SAMPLE_CONTEXT)


async def test_invalid_context_raises() -> None:
    service = QAService(make_settings(), StubLLMClient())
    with pytest.raises(InvalidInputError):
        await service.answer(SAMPLE_QUESTION, "   ")
    with pytest.raises(InvalidInputError):
        await service.answer(SAMPLE_QUESTION, "а" * 25_000)


async def test_top_k_is_forwarded_to_llm() -> None:
    client = StubLLMClient()
    service = QAService(make_settings(), client)

    result = await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT, top_k=1)

    assert len(result.citations) == 1
    assert len(client.requests[0].excerpts) == 1


async def test_prompt_contains_question_and_excerpts() -> None:
    client = StubLLMClient()
    service = QAService(make_settings(), client)

    await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    request = client.requests[0]
    assert SAMPLE_QUESTION in request.user_prompt
    assert request.excerpts
    assert all(excerpt in request.user_prompt for excerpt in request.excerpts)


async def test_metrics_are_collected() -> None:
    metrics = Metrics()
    service = QAService(make_settings(), StubLLMClient(), metrics=metrics)
    await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    snapshot = metrics.snapshot()
    assert snapshot["requests_total"] == 1
    assert snapshot["llm_calls"] == 1
    assert snapshot["answers_ok"] == 1


async def test_fallback_metrics_are_collected() -> None:
    metrics = Metrics()
    client = StubLLMClient(error=LLMUnavailableError("down"))
    service = QAService(make_settings(), client, metrics=metrics)
    await service.answer(SAMPLE_QUESTION, SAMPLE_CONTEXT)

    snapshot = metrics.snapshot()
    assert snapshot["fallbacks"] == 1
    assert snapshot["fallback_llm_error"] == 1
    assert snapshot.get("answers_ok", 0) == 0
