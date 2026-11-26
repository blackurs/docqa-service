from __future__ import annotations

from docqa.core.config import Settings
from docqa.llm.base import LLMRequest
from docqa.llm.prompts import SYSTEM_PROMPT, build_llm_request, build_user_prompt
from docqa.llm.providers.mock import MockLLMClient


def test_user_prompt_contains_numbered_excerpts_and_question() -> None:
    prompt = build_user_prompt("Какой таймаут?", ["Первый фрагмент.", "Второй фрагмент."])
    assert "[1] Первый фрагмент." in prompt
    assert "[2] Второй фрагмент." in prompt
    assert "Question: Какой таймаут?" in prompt
    assert prompt.endswith("Answer:")


def test_build_llm_request_uses_settings() -> None:
    settings = Settings(llm_max_tokens=123, llm_temperature=0.7, _env_file=None)
    request = build_llm_request("Вопрос?", ["Фрагмент."], settings)
    assert request.system_prompt == SYSTEM_PROMPT
    assert request.max_tokens == 123
    assert request.temperature == 0.7
    assert request.question == "Вопрос?"
    assert request.excerpts == ("Фрагмент.",)


def test_system_prompt_forbids_inventing_facts() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "only" in lowered
    assert "do not invent" in lowered


async def test_mock_provider_answers_with_excerpts() -> None:
    client = MockLLMClient()
    request = LLMRequest(
        system_prompt="system",
        user_prompt="user",
        question="Какой таймаут?",
        excerpts=("Таймаут 20 секунд.", "Повторных попыток две."),
    )
    response = await client.generate(request)
    assert "Таймаут 20 секунд." in response.text
    assert response.provider == "mock"
    assert response.prompt_tokens
    assert response.completion_tokens
    await client.aclose()
