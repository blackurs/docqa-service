"""Post-processing of raw model output.

LLMs are unreliable formatters: they add "Answer:" prefixes, wrap text in
markdown fences, emit trailing whitespace or return an empty string. This
module turns raw output into a predictable answer or raises a typed error so
the pipeline can fall back.
"""

from __future__ import annotations

import re

from docqa.core.errors import PostprocessingError

_PREFIX_RE = re.compile(r"^(?:answer|ответ|a)\s*[:\-—]\s*", re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?|\n?\s*```$")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_MULTI_SPACES_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINES_RE = re.compile(r"\n{3,}")


def _strip_fences(text: str) -> str:
    if text.startswith("```") or text.endswith("```"):
        return _FENCE_RE.sub("", text).strip()
    return text


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    window = text[: max_chars + 1]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("\n"))
    if cut >= max_chars // 2:
        return window[: cut + 1].strip()
    return window[:max_chars].rstrip()


def clean_answer(raw: str, *, max_chars: int = 2000) -> str:
    """Normalize a raw LLM answer or raise :class:`PostprocessingError`."""
    if raw is None:
        raise PostprocessingError("LLM returned no answer at all")

    text = str(raw).replace("\r\n", "\n").replace("\r", "\n").strip()
    text = _strip_fences(text)

    # Remove leading "Answer:" / "Ответ:" prefixes (at most 3 repetitions).
    for _ in range(3):
        stripped = _PREFIX_RE.sub("", text, count=1).strip()
        if stripped == text:
            break
        text = stripped

    text = _TRAILING_WS_RE.sub("", text)
    text = _MULTI_SPACES_RE.sub(" ", text)
    text = _MULTI_NEWLINES_RE.sub("\n\n", text)
    text = _truncate(text.strip(), max_chars).strip()

    if not text:
        raise PostprocessingError("LLM answer is empty after post-processing")
    return text
