from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import httpx
import pytest

from docqa.core.config import Settings
from docqa.core.errors import (
    LLMBadResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from docqa.llm.base import LLMRequest
from docqa.llm.providers.openai_compat import OpenAIChatClient

Handler = Callable[[httpx.Request], httpx.Response]

OK_BODY: Dict[str, Any] = {
    "model": "gpt-4o-mini",
    "choices": [{"message": {"role": "assistant", "content": "Таймаут — 20 секунд."}}],
    "usage": {"prompt_tokens": 30, "completion_tokens": 7},
}


def make_settings(**overrides: Any) -> Settings:
    values: Dict[str, Any] = {
        "llm_provider": "openai",
        "llm_api_key": "test-key",
        "llm_model": "gpt-4o-mini",
        "llm_max_retries": 1,
        "llm_retry_backoff_seconds": 0,
        "llm_timeout_seconds": 1,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def make_request() -> LLMRequest:
    return LLMRequest(system_prompt="system", user_prompt="user")


async def run_with_handler(handler: Handler, **overrides: Any) -> Any:
    settings = make_settings(**overrides)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        provider = OpenAIChatClient(settings, client=http_client)
        return await provider.generate(make_request())


async def test_successful_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OK_BODY)

    response = await run_with_handler(handler)
    assert response.text == "Таймаут — 20 секунд."
    assert response.provider == "openai"
    assert response.model == "gpt-4o-mini"
    assert response.prompt_tokens == 30
    assert response.completion_tokens == 7


async def test_request_payload_and_auth_header() -> None:
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=OK_BODY)

    await run_with_handler(handler)
    sent = captured[0]
    assert sent.headers["Authorization"] == "Bearer test-key"
    body = json.loads(sent.content)
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "user"


async def test_retries_on_server_error_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=OK_BODY)

    response = await run_with_handler(handler)
    assert response.text
    assert calls["count"] == 2


async def test_retries_exhausted_raises_unavailable() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, json={"error": "down"})

    with pytest.raises(LLMUnavailableError):
        await run_with_handler(handler)
    assert calls["count"] == 2  # 1 attempt + 1 retry


async def test_timeout_mapped_to_llm_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(LLMTimeoutError):
        await run_with_handler(handler)


async def test_rate_limit_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    with pytest.raises(LLMRateLimitError):
        await run_with_handler(handler)


async def test_client_error_is_not_retried() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(LLMBadResponseError):
        await run_with_handler(handler)
    assert calls["count"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": "   "}}]},
    ],
)
async def test_malformed_response_raises_bad_response(body: Dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(LLMBadResponseError):
        await run_with_handler(handler)


async def test_non_json_response_raises_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(LLMBadResponseError):
        await run_with_handler(handler)


async def test_no_retries_when_configured_to_zero() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500)

    with pytest.raises(LLMUnavailableError):
        await run_with_handler(handler, llm_max_retries=0)
    assert calls["count"] == 1
