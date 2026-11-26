"""LLM providers package: mock (offline) and OpenAI-compatible (real)."""

from docqa.llm.providers.mock import MockLLMClient
from docqa.llm.providers.openai_compat import OpenAIChatClient

__all__ = ["MockLLMClient", "OpenAIChatClient"]
