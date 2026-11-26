"""Client for OpenAI-compatible Chat Completions APIs.

Works with OpenAI, Azure/OpenAI proxies, vLLM, Ollama (OpenAI mode), GigaChat
or YandexGPT gateways that expose the same contract: set ``LLM_BASE_URL`` and
``LLM_MODEL``.

Reliability features:
* explicit connect/read/write timeouts;
* bounded retries with exponential backoff for timeouts, 429 and 5xx;
* no retries for 4xx (except 429) — those are caller/config errors;
* every failure is mapped to a typed :class:`docqa.core.errors.LLMError`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx

from docqa.core.config import Settings
from docqa.core.errors import (
    LLMBadResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from docqa.core.logging import get_logger, log_extra
from docqa.llm.base import LLMRequest, LLMResponse

log = get_logger(__name__)

_RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class OpenAIChatClient:
    name = "openai"

    def __init__(self, settings: Settings, *, client: Optional[httpx.AsyncClient] = None) -> None:
        self._settings = settings
        self._model = settings.llm_model
        self._url = f"{settings.llm_base_url}/chat/completions"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.llm_timeout_seconds),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        attempts = self._settings.llm_max_retries + 1
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(
                    self._url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._settings.api_key or ''}"},
                )
            except httpx.TimeoutException:
                last_error = LLMTimeoutError(f"LLM request timed out after {attempt} attempt(s)")
                log.warning(
                    "llm_timeout",
                    extra=log_extra(event="llm_timeout", attempt=attempt, error_code="llm_timeout"),
                )
            except httpx.HTTPError as exc:
                last_error = LLMUnavailableError(
                    f"LLM transport error on attempt {attempt}: {type(exc).__name__}"
                )
                log.warning(
                    "llm_transport_error",
                    extra=log_extra(
                        event="llm_transport_error",
                        attempt=attempt,
                        error_code="llm_unavailable",
                    ),
                )
            else:
                if response.status_code == 429:
                    last_error = LLMRateLimitError("LLM provider rate limit exceeded")
                    log.warning(
                        "llm_rate_limited",
                        extra=log_extra(
                            event="llm_rate_limited", attempt=attempt, error_code="llm_rate_limited"
                        ),
                    )
                elif response.status_code >= 500:
                    last_error = LLMUnavailableError(
                        f"LLM provider returned HTTP {response.status_code}"
                    )
                    log.warning(
                        "llm_server_error",
                        extra=log_extra(
                            event="llm_server_error",
                            attempt=attempt,
                            status_code=response.status_code,
                            error_code="llm_unavailable",
                        ),
                    )
                elif response.status_code >= 400:
                    # Not retryable: bad request, auth failure, unknown model, etc.
                    raise LLMBadResponseError(
                        f"LLM provider rejected the request with HTTP {response.status_code}",
                        details=[{"status_code": response.status_code}],
                    )
                else:
                    return self._parse(response, attempt)

            if attempt < attempts:
                backoff = self._settings.llm_retry_backoff_seconds * (2 ** (attempt - 1))
                if backoff:
                    await asyncio.sleep(backoff)

        assert last_error is not None  # for type checkers
        raise last_error

    def _parse(self, response: httpx.Response, attempt: int) -> LLMResponse:
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponseError(
                "LLM response has an unexpected structure",
                details=[{"reason": type(exc).__name__}],
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMBadResponseError("LLM returned an empty message")

        usage = data.get("usage") or {}
        log.info(
            "llm_response_received",
            extra=log_extra(
                event="llm_response_received",
                attempt=attempt,
                model=data.get("model", self._model),
                provider=self.name,
            ),
        )
        return LLMResponse(
            text=content,
            model=str(data.get("model") or self._model),
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
