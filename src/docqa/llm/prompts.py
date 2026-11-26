"""Prompt construction.

Prompts live in one place so they can be reviewed, versioned and unit-tested
independently from providers and HTTP handlers.
"""

from __future__ import annotations

from typing import Sequence

from docqa.core.config import Settings
from docqa.llm.base import LLMRequest

SYSTEM_PROMPT = (
    "You are a precise document question answering assistant. "
    "Answer the user's question using ONLY the provided context excerpts. "
    "If the excerpts do not contain the answer, say that the document does not cover it. "
    "Be concise (at most 3 sentences), cite excerpt numbers like [1] when useful, "
    "do not invent facts, and do not use markdown formatting."
)


def build_user_prompt(question: str, excerpts: Sequence[str]) -> str:
    numbered = "\n".join(f"[{i + 1}] {text}" for i, text in enumerate(excerpts))
    return f"Context excerpts:\n{numbered}\n\nQuestion: {question}\n\nAnswer:"


def build_llm_request(question: str, excerpts: Sequence[str], settings: Settings) -> LLMRequest:
    return LLMRequest(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(question, excerpts),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        question=question,
        excerpts=tuple(excerpts),
    )
