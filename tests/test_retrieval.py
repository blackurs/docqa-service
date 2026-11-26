from __future__ import annotations

from docqa.services.retrieval import (
    normalize_whitespace,
    rank_sentences,
    select_excerpts,
    split_sentences,
)

DOCUMENT = (
    "Компания «Пример» основана в 2010 году. "
    "Головной офис расположен в Москве. "
    "Сервис использует таймаут 20 секунд по умолчанию. "
    "Результаты кешируются на 300 секунд. "
    "Поддерживаются модели семейства GPT."
)


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("  a \n\t b  ") == "a b"


def test_split_sentences_returns_sentences() -> None:
    sentences = split_sentences(DOCUMENT)
    assert len(sentences) == 5
    assert sentences[2].startswith("Сервис использует таймаут")


def test_split_sentences_keeps_short_document() -> None:
    assert split_sentences("Короткий текст") == ["Короткий текст"]


def test_hard_wrapped_lines_are_joined() -> None:
    text = (
        "Таймаут настраивается переменной\nLLM_TIMEOUT_SECONDS. Вторая строка достаточно длинная."
    )
    assert split_sentences(text) == [
        "Таймаут настраивается переменной LLM_TIMEOUT_SECONDS.",
        "Вторая строка достаточно длинная.",
    ]


def test_numbered_list_items_are_split() -> None:
    text = "Правила:\n1. Первое правило.\n2. Второе правило."
    sentences = split_sentences(text)
    assert any("Первое правило" in sentence for sentence in sentences)
    assert any("Второе правило" in sentence for sentence in sentences)
    assert not any("1. Первое правило. 2." in sentence for sentence in sentences)


def test_relevant_sentence_ranks_first() -> None:
    question = "Какой таймаут используется по умолчанию?"
    excerpts = select_excerpts(question, DOCUMENT, top_k=1, max_chars=1200)
    assert len(excerpts) == 1
    assert "таймаут" in excerpts[0].text.lower()


def test_selection_respects_top_k_and_char_budget() -> None:
    question = "Расскажи про кеш и таймаут"
    excerpts = select_excerpts(question, DOCUMENT, top_k=2, max_chars=200)
    assert len(excerpts) <= 2
    assert sum(len(excerpt.text) for excerpt in excerpts) <= 200


def test_excerpts_are_sorted_by_relevance() -> None:
    question = "модели GPT таймаут"
    excerpts = select_excerpts(question, DOCUMENT, top_k=3, max_chars=1200)
    scores = [excerpt.score for excerpt in excerpts]
    assert scores == sorted(scores, reverse=True)
    assert [excerpt.index for excerpt in excerpts] == [1, 2, 3]


def test_no_overlap_falls_back_to_document_start() -> None:
    question = "совершенно другой запрос про погоду"
    excerpts = select_excerpts(question, DOCUMENT, top_k=2, max_chars=1200)
    assert excerpts[0].text.startswith("Компания")


def test_empty_document_returns_no_excerpts() -> None:
    assert select_excerpts("вопрос", "   \n  ", top_k=3, max_chars=1000) == []


def test_long_sentence_is_truncated() -> None:
    document = "Слово " * 500 + "конец."
    excerpts = select_excerpts("слово", document, top_k=1, max_chars=100)
    assert len(excerpts) == 1
    assert len(excerpts[0].text) <= 100


def test_rank_sentences_returns_positions_and_scores() -> None:
    ranked = rank_sentences("таймаут", split_sentences(DOCUMENT))
    assert len(ranked) == 5
    assert all(isinstance(position, int) for position, _ in ranked)
    assert max(score for _, score in ranked) > 0
