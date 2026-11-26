from __future__ import annotations

import pytest

from docqa.core.errors import PostprocessingError
from docqa.services.postprocess import clean_answer


def test_strips_whitespace() -> None:
    assert clean_answer("  hello  ") == "hello"


def test_removes_answer_prefix() -> None:
    assert clean_answer("Answer: it is 20 seconds") == "it is 20 seconds"
    assert clean_answer("Ответ: 20 секунд") == "20 секунд"
    assert clean_answer("A: 20 seconds") == "20 seconds"


def test_removes_markdown_code_fence() -> None:
    raw = "```text\nТаймаут — 20 секунд.\n```"
    assert clean_answer(raw) == "Таймаут — 20 секунд."


def test_collapses_extra_spaces_and_newlines() -> None:
    raw = "Первая строка.\n\n\n\nВторая   строка.   "
    assert clean_answer(raw) == "Первая строка.\n\nВторая строка."


def test_empty_answer_raises() -> None:
    with pytest.raises(PostprocessingError):
        clean_answer("   ")
    with pytest.raises(PostprocessingError):
        clean_answer(None)  # type: ignore[arg-type]


def test_truncates_to_sentence_boundary() -> None:
    raw = "Первое предложение. Второе предложение. Третье предложение."
    result = clean_answer(raw, max_chars=40)
    assert len(result) <= 40
    assert result.endswith(".")


def test_truncates_hard_when_no_sentence_boundary() -> None:
    result = clean_answer("x" * 500, max_chars=50)
    assert len(result) == 50


def test_preserves_internal_markdown_list_lines() -> None:
    raw = "Шаги:\n1. Первый\n2. Второй"
    assert clean_answer(raw) == raw
