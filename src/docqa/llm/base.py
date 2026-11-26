"""Contracts shared by all LLM providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple


@dataclass(frozen=True)
class LLMRequest:
    """Everything a provider needs to produce an answer.

    ``question`` and ``excerpts`` duplicate *structured* parts of the prompts.
    Real providers only need the rendered prompts; the mock provider uses the
    structured fields to generate deterministic, grounded answers.
    """

    system_prompt: str
    user_prompt: str
    temperature: float = 0.2
    max_tokens: int = 400
    question: str = ""
    excerpts: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LLMResponse:
    """Normalized provider response."""

    text: str
    model: str
    provider: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class LLMClient(Protocol):
    """Minimal async LLM interface (easy to fake in tests)."""

    name: str

    async def generate(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover
        ...

    async def aclose(self) -> None:  # pragma: no cover
        ...
