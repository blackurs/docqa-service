"""Business logic: the Q&A pipeline.

Flow:

    validate -> cache lookup -> retrieve excerpts -> build prompt -> call LLM
    -> post-process -> cache store -> return

The service knows nothing about HTTP or about a specific LLM vendor; it depends
on the :class:`docqa.llm.base.LLMClient` contract and on configuration only.
That keeps the pipeline unit-testable and lets the API and CLI share it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Callable, Optional, Tuple

from docqa.core.cache import TTLCache, build_cache_key
from docqa.core.config import Settings
from docqa.core.errors import InvalidInputError, LLMError, PostprocessingError
from docqa.core.logging import get_logger, log_extra
from docqa.core.metrics import Metrics
from docqa.llm.base import LLMClient, LLMResponse
from docqa.llm.prompts import build_llm_request
from docqa.services.postprocess import clean_answer
from docqa.services.retrieval import normalize_whitespace, select_excerpts

log = get_logger(__name__)


@dataclass(frozen=True)
class Citation:
    index: int
    text: str
    score: float


@dataclass(frozen=True)
class QAResult:
    answer: str
    citations: Tuple[Citation, ...]
    degraded: bool
    cached: bool
    provider: str
    model: str
    latency_ms: float
    degradation_reason: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class QAService:
    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        *,
        cache: Optional[TTLCache] = None,
        metrics: Optional[Metrics] = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._cache = cache
        self._metrics = metrics or Metrics()
        self._clock = clock

    @property
    def metrics(self) -> Metrics:
        return self._metrics

    @property
    def llm(self) -> LLMClient:
        return self._llm

    async def answer(
        self,
        question: str,
        context: str,
        *,
        top_k: Optional[int] = None,
        allow_fallback: bool = True,
    ) -> QAResult:
        started = self._clock()
        self._metrics.incr("requests_total")

        question_clean = self._validate_question(question)
        context_clean = self._validate_context(context)
        excerpt_limit = top_k or self._settings.top_k_excerpts

        log.info(
            "request_received",
            extra=log_extra(
                event="request_received",
                question_chars=len(question_clean),
                context_chars=len(context_clean),
            ),
        )

        cache_key = build_cache_key(
            "qa-pipeline-v1",
            self._llm.name,
            self._settings.llm_model,
            question_clean.casefold(),
            normalize_whitespace(context_clean).casefold(),
            excerpt_limit,
        )
        if self._cache is not None:
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                self._metrics.incr("cache_hits")
                latency_ms = self._elapsed_ms(started)
                log.info(
                    "cache_hit",
                    extra=log_extra(event="cache_hit", cache="hit", duration_ms=latency_ms),
                )
                return replace(cached_result, cached=True, latency_ms=latency_ms)
            self._metrics.incr("cache_misses")
            log.debug("cache_miss", extra=log_extra(event="cache_miss", cache="miss"))

        excerpts = select_excerpts(
            question_clean,
            context_clean,
            top_k=excerpt_limit,
            max_chars=self._settings.max_excerpt_chars,
        )
        if not excerpts:
            raise InvalidInputError(
                "Context does not contain any usable text",
                details=[{"field": "context", "reason": "no_sentences_found"}],
            )

        citations = tuple(
            Citation(index=excerpt.index, text=excerpt.text, score=excerpt.score)
            for excerpt in excerpts
        )
        request = build_llm_request(
            question_clean, [excerpt.text for excerpt in excerpts], self._settings
        )
        log.info(
            "prompt_built",
            extra=log_extra(
                event="prompt_built",
                excerpts=len(excerpts),
                question_chars=len(question_clean),
                context_chars=len(request.user_prompt),
            ),
        )
        log.debug("prompt_preview=%s", request.user_prompt[:300])

        try:
            llm_response: LLMResponse = await self._llm.generate(request)
        except LLMError as exc:
            self._metrics.incr("llm_errors")
            log.error(
                "llm_call_failed",
                extra=log_extra(
                    event="llm_call_failed", error_code=exc.code, provider=self._llm.name
                ),
            )
            if allow_fallback and self._settings.fallback_enabled:
                return self._fallback_result(
                    citations, exc.code, started, metrics_reason="llm_error"
                )
            raise

        self._metrics.incr("llm_calls")
        log.info(
            "model_response",
            extra=log_extra(
                event="model_response",
                provider=llm_response.provider,
                model=llm_response.model,
            ),
        )

        try:
            answer = clean_answer(llm_response.text, max_chars=self._settings.max_answer_chars)
        except PostprocessingError as exc:
            log.error(
                "postprocessing_failed",
                extra=log_extra(event="postprocessing_failed", error_code=exc.code),
            )
            if allow_fallback and self._settings.fallback_enabled:
                return self._fallback_result(
                    citations, exc.code, started, metrics_reason="postprocessing_error"
                )
            raise

        latency_ms = self._elapsed_ms(started)
        result = QAResult(
            answer=answer,
            citations=citations,
            degraded=False,
            cached=False,
            provider=llm_response.provider,
            model=llm_response.model,
            latency_ms=latency_ms,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
        )
        if self._cache is not None:
            self._cache.set(cache_key, result)

        self._metrics.incr("answers_ok")
        log.info(
            "answer_ready",
            extra=log_extra(
                event="answer_ready",
                provider=result.provider,
                model=result.model,
                duration_ms=latency_ms,
                degraded=False,
            ),
        )
        return result

    # --- internals --------------------------------------------------------

    def _fallback_result(
        self,
        citations: Tuple[Citation, ...],
        reason: str,
        started: float,
        *,
        metrics_reason: str,
    ) -> QAResult:
        self._metrics.incr("fallbacks")
        self._metrics.incr(f"fallback_{metrics_reason}")
        latency_ms = self._elapsed_ms(started)
        answer = " ".join(citation.text for citation in citations[:2]).strip()
        result = QAResult(
            answer=answer,
            citations=citations,
            degraded=True,
            cached=False,
            provider="extractive",
            model="extractive-fallback",
            latency_ms=latency_ms,
            degradation_reason=reason,
            prompt_tokens=0,
            completion_tokens=0,
        )
        log.warning(
            "fallback_used",
            extra=log_extra(
                event="fallback_used",
                error_code=reason,
                provider=result.provider,
                model=result.model,
                duration_ms=latency_ms,
                degraded=True,
            ),
        )
        return result

    def _validate_question(self, question: str) -> str:
        value = normalize_whitespace(question)
        if len(value) < self._settings.min_question_chars:
            raise InvalidInputError(
                f"Question must contain at least {self._settings.min_question_chars} characters",
                details=[{"field": "question", "reason": "too_short"}],
            )
        if len(value) > self._settings.max_question_chars:
            raise InvalidInputError(
                f"Question must not exceed {self._settings.max_question_chars} characters",
                details=[{"field": "question", "reason": "too_long"}],
            )
        return value

    def _validate_context(self, context: str) -> str:
        value = (context or "").strip()
        if not value:
            raise InvalidInputError(
                "Context must not be blank",
                details=[{"field": "context", "reason": "blank"}],
            )
        if len(value) > self._settings.max_context_chars:
            raise InvalidInputError(
                f"Context must not exceed {self._settings.max_context_chars} characters",
                details=[{"field": "context", "reason": "too_long"}],
            )
        return value

    def _elapsed_ms(self, started: float) -> float:
        return round((self._clock() - started) * 1000, 3)


__all__ = ["Citation", "QAResult", "QAService"]
