from __future__ import annotations

import pytest

from docqa.core.errors import LLMTimeoutError, LLMUnavailableError
from docqa.llm.base import LLMRequest
from docqa.llm.providers.mock import MockLLMClient


def make_request() -> LLMRequest:
    return LLMRequest(
        system_prompt="system",
        user_prompt="user",
        question="Вопрос?",
        excerpts=("Первый фрагмент.", "Второй фрагмент."),
    )


async def test_answers_with_first_two_excerpts() -> None:
    client = MockLLMClient()
    response = await client.generate(make_request())
    assert response.text == "Первый фрагмент. Второй фрагмент."
    assert response.model == "mock-qa-1"
    assert response.provider == "mock"


async def test_empty_excerpts_answer_question_placeholder() -> None:
    client = MockLLMClient()
    request = LLMRequest(system_prompt="s", user_prompt="u", question="Что?", excerpts=())
    response = await client.generate(request)
    assert "Что?" in response.text


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("timeout", LLMTimeoutError), ("error", LLMUnavailableError)],
)
async def test_simulated_failures(mode: str, expected: type[Exception]) -> None:
    client = MockLLMClient(fail_mode=mode)
    with pytest.raises(expected):
        await client.generate(make_request())


async def test_empty_mode_returns_blank_text() -> None:
    client = MockLLMClient(fail_mode="empty")
    response = await client.generate(make_request())
    assert response.text.strip() == ""


async def test_latency_is_applied() -> None:
    client = MockLLMClient(latency_ms=1)
    response = await client.generate(make_request())
    assert response.text
