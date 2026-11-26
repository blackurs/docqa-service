"""Deterministic mock provider.

Used for local demos, offline development and CI:
* no API key, no network, no cost;
* supports simulated failures (``MOCK_FAIL_MODE``) to demonstrate fallback
  behaviour without unplugging anything.
"""

from __future__ import annotations

import asyncio

from docqa.core.errors import LLMTimeoutError, LLMUnavailableError
from docqa.core.logging import get_logger, log_extra
from docqa.llm.base import LLMRequest, LLMResponse

log = get_logger(__name__)


class MockLLMClient:
    """Fake LLM that answers with the most relevant excerpts."""

    name = "mock"

    def __init__(
        self,
        model: str = "mock-qa-1",
        latency_ms: int = 0,
        fail_mode: str = "none",
    ) -> None:
        self._model = model
        self._latency_ms = latency_ms
        self._fail_mode = fail_mode

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if self._latency_ms:
            await asyncio.sleep(self._latency_ms / 1000)

        if self._fail_mode == "timeout":
            raise LLMTimeoutError("Mock provider simulated a timeout")
        if self._fail_mode == "error":
            raise LLMUnavailableError("Mock provider simulated an outage")
        if self._fail_mode == "empty":
            log.warning("mock_empty_answer", extra=log_extra(event="mock_empty_answer"))
            return LLMResponse(text="   ", model=self._model, provider=self.name)

        answer = " ".join(request.excerpts[:2]).strip()
        if not answer:
            answer = f"Mock answer to: {request.question}"

        # Rough estimate ~4 chars per token; keeps usage fields realistic.
        prompt_tokens = max(1, len(request.system_prompt + request.user_prompt) // 4)
        completion_tokens = max(1, len(answer) // 4)
        return LLMResponse(
            text=answer,
            model=self._model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def aclose(self) -> None:
        return None
